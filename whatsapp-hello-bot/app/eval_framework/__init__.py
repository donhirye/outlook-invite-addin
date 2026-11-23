"""Eval framework — answering-strategy bake-offs (validation only).

This package is for comparing designs (A / C / E / Ep) on an eval set.
It is NOT the long-term product architecture.

Enable with EVAL_FRAMEWORK_ENABLED=true, then pick ANSWER_STRATEGY=A|C|E|Ep.
When the flag is off, Engine 1 uses the single default path (Ep) and ignores
strategy switching.

Reusable entry: `evals.framework` re-exports this package for harness scripts.
"""

from __future__ import annotations

from app.engines.base import AnswerResult, ConversationContext

from . import strategy_a, strategy_c, strategy_e, strategy_ep

STRATEGY_MODULES = {
    strategy_a.STRATEGY_ID: strategy_a,
    strategy_c.STRATEGY_ID: strategy_c,
    strategy_e.STRATEGY_ID: strategy_e,
    strategy_ep.STRATEGY_ID: strategy_ep,
}

# Aliases for E′
STRATEGY_ALIASES = {
    "EPRIME": "Ep",
    "E_PRIME": "Ep",
    "E'": "Ep",
    "E′": "Ep",
    "EP": "Ep",
}

# When eval framework is off, always answer with this design.
DEFAULT_LIVE_STRATEGY = strategy_ep.STRATEGY_ID


def normalize_strategy_id(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return DEFAULT_LIVE_STRATEGY
    if text in STRATEGY_MODULES:
        return text
    folded = text.upper().replace("′", "'").replace(" ", "")
    if folded in STRATEGY_ALIASES:
        return STRATEGY_ALIASES[folded]
    if folded in STRATEGY_MODULES:
        return folded
    raise ValueError(
        f"Unknown ANSWER_STRATEGY={raw!r}. "
        f"Use one of: {', '.join(STRATEGY_MODULES)} "
        "(Ep aliases: Ep, EP, Eprime, E')"
    )


def get_strategy(strategy_id: str | None = None):
    sid = (
        normalize_strategy_id(strategy_id)
        if strategy_id is not None
        else resolve_strategy_id()
    )
    return STRATEGY_MODULES[sid]


def resolve_strategy_id(
    *,
    override: str | None = None,
) -> str:
    """Which strategy will run (honors eval-framework flag + optional override)."""
    from app.config import ANSWER_STRATEGY, EVAL_FRAMEWORK_ENABLED

    if not EVAL_FRAMEWORK_ENABLED:
        return DEFAULT_LIVE_STRATEGY
    if override:
        return normalize_strategy_id(override)
    return normalize_strategy_id(ANSWER_STRATEGY)


def list_strategies() -> list[dict[str, str]]:
    return [
        {"id": m.STRATEGY_ID, "title": m.STRATEGY_TITLE}
        for m in (
            strategy_a,
            strategy_c,
            strategy_e,
            strategy_ep,
        )
    ]


def run_strategy(
    ctx: ConversationContext,
    *,
    engine,
    strategy_id: str | None = None,
) -> AnswerResult:
    mod = get_strategy(strategy_id)
    return mod.answer(ctx, engine=engine)
