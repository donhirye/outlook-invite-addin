"""Strategy E — dual-retrieve calendar + FAQ; merge whenever both hit.

No looks-like gate. No FAQ siblings. Timing/status asks still defer to LLM inside
faq_service. Weak FAQ hits can still merge onto a good calendar answer.
"""

from __future__ import annotations

from . import common
from app.calendar_service import lookup_calendar_for_topic
from app.engines.base import AnswerResult, ConversationContext
from app.faq_service import answer_faq_detailed

STRATEGY_ID = "E"
STRATEGY_TITLE = "Dual-retrieve; always merge on double hit"


def answer(ctx: ConversationContext, *, engine) -> AnswerResult:
    early = common.help_or_privacy(ctx, engine=engine)
    if early:
        return early

    overview = common.overview_result(ctx, engine=engine)
    if overview:
        return overview

    text = (ctx.text or "").strip()
    cal = lookup_calendar_for_topic(text)
    faq_direct = answer_faq_detailed(text, allow_rag=False)
    cal_hit = bool(cal.get("hit") and cal.get("answer"))
    faq_hit = common.faq_is_hit(faq_direct.answer)

    if cal_hit and not faq_hit:
        return common.calendar_result(cal, engine=engine)
    if faq_hit and not cal_hit:
        return common.faq_result(faq_direct, engine=engine)
    if cal_hit and faq_hit:
        return common.merge_calendar_faq(cal, faq_direct, engine=engine)

    faq = answer_faq_detailed(text, allow_rag=True)
    return common.faq_result(faq, engine=engine)
