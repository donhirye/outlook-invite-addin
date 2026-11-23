"""Live Engine 1 answer path (former Ep).

Dual-retrieve calendar + FAQ. When both hit:
  - action/how-to/cost/register → merge
  - otherwise calendar wins
"""

from __future__ import annotations

from app.calendar_service import is_faq_action_question, lookup_calendar_for_topic
from app.engines import answer_builders as builders
from app.engines.base import AnswerResult, ConversationContext
from app.faq_service import answer_faq_detailed

LIVE_PATH_ID = "Ep"


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
    faq_hit = builders.faq_is_hit(faq_direct.answer)

    if cal_hit and not faq_hit:
        return builders.calendar_result(cal, engine=engine)
    if faq_hit and not cal_hit:
        return builders.faq_result(faq_direct, engine=engine)
    if cal_hit and faq_hit:
        if is_faq_action_question(text):
            return builders.merge_calendar_faq(cal, faq_direct, engine=engine)
        return builders.calendar_result(cal, engine=engine)

    faq = answer_faq_detailed(text, allow_rag=True)
    return builders.faq_result(faq, engine=engine)
