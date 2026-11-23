"""Engine 1 — dispatches to ANSWER_STRATEGY (A | C | E | Ep)."""

from __future__ import annotations

from app.answer_strategies import normalize_strategy_id, run_strategy
from app.config import ANSWER_STRATEGY
from app.engines.base import ENGINE_1, AnswerResult, ConversationContext
from app.engines.registry import register_engine


class LegacyEngine:
    id = ENGINE_1
    version = "1.0.0"
    title = "Engine 1 — Legacy baseline"
    implemented = True

    def answer(self, ctx: ConversationContext) -> AnswerResult:
        # Per-call override via ctx.extras["answer_strategy"] (evals); else env.
        override = None
        if isinstance(ctx.extras, dict):
            override = ctx.extras.get("answer_strategy")
        sid = normalize_strategy_id(override or ANSWER_STRATEGY)
        result = run_strategy(ctx, engine=self, strategy_id=sid)
        result.answer_strategy = sid
        return result


register_engine(LegacyEngine())
