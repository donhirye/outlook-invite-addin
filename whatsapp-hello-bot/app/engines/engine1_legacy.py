"""Engine 1 — live dual-retrieve answer path (Ep)."""

from __future__ import annotations

from app.engines.answer_path import LIVE_PATH_ID, answer as answer_live
from app.engines.base import ENGINE_1, AnswerResult, ConversationContext
from app.engines.registry import register_engine


class LegacyEngine:
    id = ENGINE_1
    version = "1.0.0"
    title = "Engine 1 — Legacy baseline"
    implemented = True

    def answer(self, ctx: ConversationContext) -> AnswerResult:
        result = answer_live(ctx, engine=self)
        result.answer_strategy = LIVE_PATH_ID
        return result


register_engine(LegacyEngine())
