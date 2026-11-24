"""Live Engine 1 answer path (former Ep).

Dual-retrieve calendar + FAQ. When both hit:
  - action/how-to/cost/register OR descriptive what-is/about → merge
  - otherwise calendar wins

For weak FAQ pointer hits (e.g. Fall Fest for "clubs?"), keep searching FAQ
RAG then optional newsletter sections; may lead with the opportunity.
"""

from __future__ import annotations

from app.calendar_service import lookup_calendar_for_topic, should_merge_calendar_faq
from app.engines import answer_builders as builders
from app.engines.base import AnswerResult, ConversationContext
from app.faq_service import FaqAnswer, answer_faq_detailed

LIVE_PATH_ID = "Ep"


def _with_opportunity(opportunity: FaqAnswer | None, detail: FaqAnswer) -> FaqAnswer:
    if opportunity is None or not builders.faq_is_hit(opportunity.answer):
        return detail
    if not builders.faq_is_hit(detail.answer):
        return opportunity
    combined = builders.combine_opportunity_with_detail(
        opportunity.answer, detail.answer
    )
    sources = []
    for part in (opportunity.source_name, detail.source_name):
        if part and part not in sources:
            sources.append(part)
    chunks: list[str] = []
    for part in (opportunity, detail):
        chunks.extend(list(getattr(part, "retrieved_chunks", None) or []))
    return FaqAnswer(
        answer=combined,
        confidence=detail.confidence or opportunity.confidence,
        match_score=detail.match_score or opportunity.match_score,
        retrieval_mode=detail.retrieval_mode or opportunity.retrieval_mode,
        llm_invocations=int(opportunity.llm_invocations or 0)
        + int(detail.llm_invocations or 0),
        faq_id=detail.faq_id or opportunity.faq_id,
        source_name="; ".join(sources) if sources else detail.source_name,
        source_url=detail.source_url or opportunity.source_url,
        input_tokens=(
            (detail.input_tokens or 0) + (opportunity.input_tokens or 0)
        )
        or None,
        output_tokens=(
            (detail.output_tokens or 0) + (opportunity.output_tokens or 0)
        )
        or None,
        retrieved_chunks=chunks,
    )


def answer(ctx: ConversationContext, *, engine) -> AnswerResult:
    early = builders.help_or_privacy(ctx, engine=engine)
    if early:
        return early

    overview = builders.overview_result(ctx, engine=engine)
    if overview:
        return overview

    text = (ctx.text or "").strip()
    cal = lookup_calendar_for_topic(text)
    faq_direct = answer_faq_detailed(text, allow_rag=False)
    cal_hit = bool(cal.get("hit") and cal.get("answer"))
    faq_direct_hit = builders.faq_is_hit(faq_direct.answer)
    faq_direct_full = builders.faq_fully_answers(text, faq_direct.answer)

    # Strong FAQ Q/A (answers the ask) — same early exits as before.
    if cal_hit and not faq_direct_hit:
        return builders.calendar_result(cal, engine=engine)
    if faq_direct_hit and faq_direct_full and not cal_hit:
        return builders.faq_result(faq_direct, engine=engine)
    if cal_hit and faq_direct_hit and faq_direct_full:
        if should_merge_calendar_faq(text):
            return builders.merge_calendar_faq(cal, faq_direct, engine=engine)
        return builders.calendar_result(cal, engine=engine)

    # Weak FAQ pointer (e.g. Fall Fest for "clubs") — keep as opportunity, search on.
    opportunity: FaqAnswer | None = None
    if faq_direct_hit and not faq_direct_full:
        opportunity = faq_direct

    # force_rag skips the same direct Q/A early-return so we actually scan FAQ RAG.
    faq = answer_faq_detailed(
        text, allow_rag=True, force_rag=opportunity is not None
    )
    if builders.faq_fully_answers(text, faq.answer):
        return builders.faq_result(_with_opportunity(opportunity, faq), engine=engine)

    # Optional safety net: newsletter HTML/section RAG after FAQ miss / weak hit.
    from app.config import USE_NEWSLETTER_SECTION_RAG

    if USE_NEWSLETTER_SECTION_RAG:
        try:
            from app.newsletter_section_rag import answer_from_newsletter_sections

            section = answer_from_newsletter_sections(text)
        except Exception:
            section = None
        if section is not None and builders.faq_fully_answers(text, section.answer):
            return builders.faq_result(
                _with_opportunity(opportunity, section), engine=engine
            )

    # Nothing better found — return opportunity alone, else FAQ miss/weak answer.
    if opportunity is not None:
        return builders.faq_result(opportunity, engine=engine)
    if builders.faq_is_hit(faq.answer):
        return builders.faq_result(faq, engine=engine)
    if cal_hit:
        return builders.calendar_result(cal, engine=engine)
    return builders.faq_result(faq, engine=engine)
