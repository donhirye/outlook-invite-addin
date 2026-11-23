"""Strategy C — overview (tight + reshape) + gated calendar → FAQ.

Month / what's-going-on asks use overview. Topic asks still use the looks-like
calendar gate (Party in the Park without 'when' can miss).
"""

from __future__ import annotations

from . import common
from app.calendar_service import answer_calendar_question, looks_like_calendar_question
from app.engines.base import AnswerResult, ConversationContext
from app.faq_service import answer_faq_detailed

STRATEGY_ID = "C"
STRATEGY_TITLE = "Overview + gated calendar → FAQ/RAG"


def answer(ctx: ConversationContext, *, engine) -> AnswerResult:
    early = common.help_or_privacy(ctx, engine=engine)
    if early:
        return early

    overview = common.overview_result(ctx, engine=engine)
    if overview:
        return overview

    text = (ctx.text or "").strip()
    if looks_like_calendar_question(text):
        cal = answer_calendar_question(text)
        ans = (cal.get("answer") or "").strip()
        if cal.get("handled") and ans:
            soft = "could not find" in ans.lower() or "couldn't find" in ans.lower()
            if not soft:
                return common.calendar_result(cal, engine=engine)

    faq = answer_faq_detailed(text, allow_rag=True)
    return common.faq_result(faq, engine=engine)
