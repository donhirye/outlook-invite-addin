"""Strategy A — production base: looks-like calendar gate, then FAQ (+ RAG).

No overview dual-source path. Named events without a time cue miss calendar.
"""

from __future__ import annotations

from . import common
from app.calendar_service import answer_calendar_question, looks_like_calendar_question
from app.engines.base import AnswerResult, ConversationContext
from app.faq_service import answer_faq_detailed

STRATEGY_ID = "A"
STRATEGY_TITLE = "Base (prod): gated calendar → FAQ/RAG"


def answer(ctx: ConversationContext, *, engine) -> AnswerResult:
    early = common.help_or_privacy(ctx, engine=engine)
    if early:
        return early

    text = (ctx.text or "").strip()
    if looks_like_calendar_question(text):
        cal = answer_calendar_question(text)
        if cal.get("handled") and cal.get("answer"):
            # Soft misses still count as handled in older calendar path; treat
            # empty/"could not find" as miss so FAQ can run.
            ans = cal.get("answer") or ""
            if "could not find" not in ans.lower() and "couldn't find" not in ans.lower():
                return common.calendar_result(cal, engine=engine)

    faq = answer_faq_detailed(text, allow_rag=True)
    return common.faq_result(faq, engine=engine)
