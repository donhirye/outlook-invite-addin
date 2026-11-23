"""Selectable answering strategies for eval / staging A-B.

Set ANSWER_STRATEGY to one of: A | C | E | Ep
  A  — production base (gated calendar → FAQ)
  C  — overview + gated calendar → FAQ
  E  — dual-retrieve; merge whenever both hit
  Ep — dual-retrieve; calendar wins unless how-to (E′)
"""

from __future__ import annotations

from typing import Callable

from app.engines.base import AnswerResult, ConversationContext

from app.answer_strategies import strategy_a, strategy_c, strategy_e, strategy_ep

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


def normalize_strategy_id(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return strategy_e.STRATEGY_ID  # current staging default
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
    from app.config import ANSWER_STRATEGY

    sid = normalize_strategy_id(strategy_id if strategy_id is not None else ANSWER_STRATEGY)
    return STRATEGY_MODULES[sid]


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
