"""Shared helpers for answer strategies (help / privacy / FAQ / calendar builders)."""

from __future__ import annotations

from app.config import FAQ_NOT_FOUND_MESSAGE, OPENAI_MODEL, PARENT_FALLBACK_MESSAGE
from app.engines.base import AnswerResult, ConversationContext, ModelUsage
from app.faq_admin import HELP_TEXT, format_parent_answer, is_help_command
from app.overview_service import answer_overview, is_overview_question
from app.privacy_filter import privacy_reply_if_needed


def faq_is_hit(raw: str | None) -> bool:
    text = (raw or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith("sorry,"):
        return False
    if "couldn't find that information" in lowered:
        return False
    if text.strip() == FAQ_NOT_FOUND_MESSAGE.strip():
        return False
    if text.strip() == PARENT_FALLBACK_MESSAGE.strip():
        return False
    return True


def help_or_privacy(ctx: ConversationContext, *, engine) -> AnswerResult | None:
    text = (ctx.text or "").strip()
    if is_help_command(text):
        return AnswerResult(
            messages=[HELP_TEXT],
            route="help",
            engine_id=engine.id,
            engine_version=engine.version,
        )
    privacy = privacy_reply_if_needed(text)
    if privacy:
        return AnswerResult(
            messages=[privacy],
            route="privacy_filter",
            engine_id=engine.id,
            engine_version=engine.version,
            intent="privacy",
            answer_outcome="answered",
            sources=["ptsa_privacy_policy"],
        )
    return None


def overview_result(ctx: ConversationContext, *, engine) -> AnswerResult | None:
    text = (ctx.text or "").strip()
    if not is_overview_question(text):
        return None
    overview = answer_overview(text)
    if not overview:
        return None
    llm_n = int(overview.get("llm_invocations") or 0)
    return AnswerResult(
        messages=overview["messages"],
        route="overview",
        engine_id=engine.id,
        engine_version=engine.version,
        intent="overview",
        sources=list(overview.get("sources") or []),
        answer_outcome=overview.get("answer_outcome") or "answered",
        retrieval_mode=overview.get("retrieval_mode") or "overview",
        retrieved_chunks=list(overview.get("retrieved_chunks") or []),
        source_name=overview.get("source_name"),
        source_url=overview.get("source_url"),
        faq_id=overview.get("faq_id"),
        fallback=overview.get("fallback"),
        model_usage=ModelUsage(
            model=overview.get("model") if llm_n else None,
            invocations=llm_n,
            input_tokens=overview.get("input_tokens")
            if isinstance(overview.get("input_tokens"), int)
            else None,
            output_tokens=overview.get("output_tokens")
            if isinstance(overview.get("output_tokens"), int)
            else None,
        ),
    )


def faq_result(faq, *, engine) -> AnswerResult:
    raw = faq.answer
    answer = format_parent_answer(
        raw,
        source_name=faq.source_name,
        source_url=faq.source_url,
    )
    lowered = (raw or "").strip().lower()
    if not raw or lowered.startswith("sorry,"):
        fallback = "faq_fallback"
        outcome = "unanswered"
    elif "couldn't find that information" in lowered:
        fallback = "faq_not_found"
        outcome = "unanswered"
    else:
        fallback = None
        outcome = "answered"
    return AnswerResult(
        messages=[answer],
        route="faq",
        engine_id=engine.id,
        engine_version=engine.version,
        intent="faq",
        sources=["faq_records"],
        model_usage=ModelUsage(
            model=OPENAI_MODEL if faq.llm_invocations else None,
            invocations=faq.llm_invocations,
            input_tokens=getattr(faq, "input_tokens", None),
            output_tokens=getattr(faq, "output_tokens", None),
        ),
        fallback=fallback,
        answer_outcome=outcome,
        faq_id=faq.faq_id,
        faq_match_score=faq.match_score,
        answer_confidence=faq.confidence,
        retrieval_mode=faq.retrieval_mode,
        retrieved_chunks=list(getattr(faq, "retrieved_chunks", None) or []),
        source_name=faq.source_name,
        source_url=faq.source_url,
    )


def calendar_result(cal: dict, *, engine) -> AnswerResult:
    return AnswerResult(
        messages=[cal["answer"]],
        route="calendar",
        engine_id=engine.id,
        engine_version=engine.version,
        intent="calendar",
        sources=["school_calendar"],
        answer_outcome="answered",
        source_name=cal.get("source_name"),
        source_url=cal.get("source_url"),
        retrieval_mode="calendar",
    )


def merge_calendar_faq(cal: dict, faq, *, engine) -> AnswerResult:
    faq_body = format_parent_answer(
        faq.answer,
        source_name=faq.source_name,
        source_url=faq.source_url,
    )
    merged = f"{cal['answer'].rstrip()}\n\n{faq_body}"
    chunks = list(getattr(faq, "retrieved_chunks", None) or [])
    if cal.get("answer"):
        chunks = [f"[calendar]\n{cal['answer']}", *chunks]
    return AnswerResult(
        messages=[merged],
        route="calendar_faq",
        engine_id=engine.id,
        engine_version=engine.version,
        intent="calendar_faq",
        sources=["school_calendar", "faq_records"],
        answer_outcome="answered",
        faq_id=faq.faq_id,
        faq_match_score=faq.match_score,
        answer_confidence=faq.confidence,
        retrieval_mode="calendar_faq",
        retrieved_chunks=chunks,
        source_name=cal.get("source_name") or faq.source_name,
        source_url=cal.get("source_url") or faq.source_url,
        model_usage=ModelUsage(
            model=OPENAI_MODEL if faq.llm_invocations else None,
            invocations=faq.llm_invocations,
            input_tokens=getattr(faq, "input_tokens", None),
            output_tokens=getattr(faq, "output_tokens", None),
        ),
    )
