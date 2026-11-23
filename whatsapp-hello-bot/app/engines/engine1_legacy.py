"""Engine 1 — live Ep answer path."""

from __future__ import annotations

from app.eval_framework import LIVE_STRATEGY_ID, answer as answer_ep
from app.engines.base import ENGINE_1, AnswerResult, ConversationContext
from app.engines.registry import register_engine


class LegacyEngine:
    id = ENGINE_1
    version = "1.0.0"
    title = "Engine 1 — Legacy baseline"
    implemented = True

    def answer(self, ctx: ConversationContext) -> AnswerResult:
        result = answer_ep(ctx, engine=self)
        result.answer_strategy = LIVE_STRATEGY_ID
        return result


register_engine(LegacyEngine())
