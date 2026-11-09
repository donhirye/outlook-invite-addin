"""Engine registration and lookup."""

from __future__ import annotations

from typing import Any

from app.engines.base import (
    ENGINE_1,
    ENGINE_2,
    ENGINE_3,
    ENGINE_4,
    AnsweringEngine,
    IMPLEMENTED_ENGINES,
)


_REGISTRY: dict[str, AnsweringEngine] = {}


def register_engine(engine: AnsweringEngine) -> None:
    _REGISTRY[engine.id] = engine


def get_engine(engine_id: str) -> AnsweringEngine | None:
    return _REGISTRY.get(engine_id)


def list_engines() -> list[dict[str, Any]]:
    # Lazy import to register implementations.
    from app.engines import engine1_legacy, engine2_hybrid, stubs  # noqa: F401

    engines = []
    for eid in (ENGINE_1, ENGINE_2, ENGINE_3, ENGINE_4):
        eng = _REGISTRY.get(eid)
        if not eng:
            continue
        engines.append(
            {
                "id": eng.id,
                "title": eng.title,
                "version": eng.version,
                "implemented": bool(eng.implemented),
                "selectable": bool(eng.implemented and eng.id in IMPLEMENTED_ENGINES),
            }
        )
    return engines


def ensure_registered() -> None:
    from app.engines import engine1_legacy, engine2_hybrid, stubs  # noqa: F401

    if ENGINE_1 not in _REGISTRY:
        raise RuntimeError("Engine 1 failed to register")
