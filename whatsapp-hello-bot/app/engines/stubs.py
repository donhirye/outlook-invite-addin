"""Reserved engines 3 and 4 (not implemented)."""

from __future__ import annotations

from app.engines.base import ENGINE_3, ENGINE_4, AnswerResult, ConversationContext
from app.engines.registry import register_engine


class ReservedEngine:
    implemented = False

    def __init__(self, engine_id: str, title: str, version: str = "0.0.0") -> None:
        self.id = engine_id
        self.title = title
        self.version = version

    def answer(self, ctx: ConversationContext) -> AnswerResult:
        return AnswerResult(
            messages=[
                "This answering engine is not implemented yet. "
                "An administrator should switch back to Engine 1 or Engine 2."
            ],
            route="error",
            engine_id=self.id,
            engine_version=self.version,
            error="engine_not_implemented",
            fallback="unimplemented",
        )


register_engine(ReservedEngine(ENGINE_3, "Engine 3 — Reserved (not implemented)"))
register_engine(ReservedEngine(ENGINE_4, "Engine 4 — Reserved (not implemented)"))
