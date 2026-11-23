"""Engine 1 — live path Ep; optional eval-framework strategy switch."""

from __future__ import annotations

from app.eval_framework import resolve_strategy_id, run_strategy
from app.engines.base import ENGINE_1, AnswerResult, ConversationContext
from app.engines.registry import register_engine


class LegacyEngine:
    id = ENGINE_1
    version = "1.0.0"
    title = "Engine 1 — Legacy baseline"
    implemented = True

    def answer(self, ctx: ConversationContext) -> AnswerResult:
        # Eval bake-off override via ctx.extras["answer_strategy"] only honored
        # when EVAL_FRAMEWORK_ENABLED (see resolve_strategy_id).
        override = None
        if isinstance(ctx.extras, dict):
            override = ctx.extras.get("answer_strategy")
        sid = resolve_strategy_id(override=override)
        result = run_strategy(ctx, engine=self, strategy_id=sid)
        result.answer_strategy = sid
        return result


register_engine(LegacyEngine())
