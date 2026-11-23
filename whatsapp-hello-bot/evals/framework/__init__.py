"""Reusable eval framework for answering-strategy bake-offs.

Use this package when validating designs side-by-side (CSV / harness), not as
the product's permanent architecture.

Implementation lives in ``app.eval_framework`` (must ship in the Cloud Run
image so staging can flip strategies). This module is the stable import path
for local harness scripts:

    from evals.framework import list_strategies, run_strategy, resolve_strategy_id

Flags (see ``.env.example``):
  EVAL_FRAMEWORK_ENABLED=true   # allow A|C|E|Ep switching
  ANSWER_STRATEGY=Ep            # which design when enabled

When EVAL_FRAMEWORK_ENABLED is false, the live bot always uses Ep.
"""

from __future__ import annotations

from app.eval_framework import (
    DEFAULT_LIVE_STRATEGY,
    STRATEGY_MODULES,
    get_strategy,
    list_strategies,
    normalize_strategy_id,
    resolve_strategy_id,
    run_strategy,
)

__all__ = [
    "DEFAULT_LIVE_STRATEGY",
    "STRATEGY_MODULES",
    "get_strategy",
    "list_strategies",
    "normalize_strategy_id",
    "resolve_strategy_id",
    "run_strategy",
]
