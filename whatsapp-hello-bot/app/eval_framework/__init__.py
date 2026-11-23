"""Live answer path (Ep) — dual-retrieve; calendar wins unless how-to merge.

Former A/C/E bake-off strategies and EVAL_FRAMEWORK_ENABLED switching were removed.
Pinned regression prompts live in ``evals/eval_set.md`` (reference only).
"""

from __future__ import annotations

from app.engines.base import AnswerResult, ConversationContext

from . import strategy_ep

LIVE_STRATEGY_ID = strategy_ep.STRATEGY_ID


def answer(ctx: ConversationContext, *, engine) -> AnswerResult:
    """Run the single live answering path (Ep)."""
    return strategy_ep.answer(ctx, engine=engine)
