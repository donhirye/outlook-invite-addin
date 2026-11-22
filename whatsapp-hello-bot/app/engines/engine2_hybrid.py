"""Engine 2 — thin wrapper; guided flows removed (delegates to Engine 1)."""

from __future__ import annotations

from app.engines.base import ENGINE_2, AnswerResult, ConversationContext
from app.engines.engine1_legacy import LegacyEngine
from app.engines.registry import register_engine


class HybridEngine:
    id = ENGINE_2
    version = "2.1.0"
    title = "Engine 2 — Context-aware hybrid (guided removed)"
    implemented = True

    def __init__(self) -> None:
        self._legacy = LegacyEngine()

    def answer(self, ctx: ConversationContext) -> AnswerResult:
        result = self._legacy.answer(ctx)
        result.engine_id = self.id
        result.engine_version = self.version
        return result


register_engine(HybridEngine())
