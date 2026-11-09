"""Shared message processing pipeline around interchangeable engines."""

from __future__ import annotations

import time
from typing import Any

from app.engine_config import (
    clear_pin,
    get_pinned_engine,
    get_selected_engine_id,
    pin_engine,
)
from app.engines.base import ENGINE_1, AnswerResult, ConversationContext
from app.engines.registry import ensure_registered, get_engine
from app.guided_state import get_session
from app.observability.privacy import phone_hash
from app.observability.tracing import finalize_trace, new_trace


def resolve_engine_id(phone: str) -> str:
    ensure_registered()
    session = get_session(phone)
    pinned = get_pinned_engine(phone)
    if session and pinned:
        return pinned
    selected = get_selected_engine_id()
    engine = get_engine(selected)
    if not engine or not engine.implemented:
        return ENGINE_1
    return selected


def process_message(
    *,
    phone: str,
    text: str,
    message_id: str = "",
    message_type: str = "text",
) -> AnswerResult:
    ensure_registered()
    engine_id = resolve_engine_id(phone)
    engine = get_engine(engine_id) or get_engine(ENGINE_1)
    assert engine is not None

    # Pin engine for active guided conversations.
    session = get_session(phone)
    if session and not get_pinned_engine(phone):
        pin_engine(phone, engine.id)
    if not session and get_pinned_engine(phone):
        # Clear pin when no active guided session so admin can switch engines.
        clear_pin(phone)
        engine_id = get_selected_engine_id()
        engine = get_engine(engine_id) or engine

    ctx = ConversationContext(
        phone_hash=phone_hash(phone),
        phone=phone,
        message_id=message_id,
        text=text,
        message_type=message_type,
        guided_session=get_session(phone),
        pinned_engine_id=get_pinned_engine(phone),
    )
    trace = new_trace(phone, message_id, engine.id)
    trace.span("engine_selected", engine_id=engine.id, version=engine.version)
    started = time.perf_counter()
    try:
        result = engine.answer(ctx)
        trace.span(
            "answered",
            route=result.route,
            flow_id=result.flow_id,
            step_id=result.step_id,
        )
    except Exception as exc:
        result = AnswerResult(
            messages=[
                "Sorry, I'm having trouble answering right now. Please try again shortly."
            ],
            route="error",
            engine_id=engine.id,
            engine_version=engine.version,
            error=str(exc),
            fallback="exception",
        )
        trace.span("error", error=str(exc))
    latency_ms = (time.perf_counter() - started) * 1000
    finalize_trace(trace, result, latency_ms=latency_ms)
    return result


def process_message_dict(**kwargs: Any) -> dict[str, Any]:
    result = process_message(**kwargs)
    return {
        "messages": result.messages,
        "choices": result.choices,
        "route": result.route,
        "engine_id": result.engine_id,
        "flow_id": result.flow_id,
        "step_id": result.step_id,
        "ended": result.ended,
    }
