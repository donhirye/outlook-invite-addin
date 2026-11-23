"""Strategy Ep (E′) — dual-retrieve; merge only for how-to / action asks.

Same retrieve as E, but when both calendar and FAQ hit:
  - action/how-to/cost/register → merge
  - otherwise calendar wins (avoids website FAQ dumping under 'next PTSA meeting')
"""

from __future__ import annotations

from app.answer_strategies import common
from app.calendar_service import is_faq_action_question, lookup_calendar_for_topic
from app.engines.base import AnswerResult, ConversationContext
from app.faq_service import answer_faq_detailed

STRATEGY_ID = "Ep"
STRATEGY_TITLE = "Dual-retrieve; calendar wins unless how-to merge"


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
        if is_faq_action_question(text):
            return common.merge_calendar_faq(cal, faq_direct, engine=engine)
        return common.calendar_result(cal, engine=engine)

    faq = answer_faq_detailed(text, allow_rag=True)
    return common.faq_result(faq, engine=engine)
