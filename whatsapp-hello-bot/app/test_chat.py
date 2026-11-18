"""Staging-only Test Chat: browser chat + JSON endpoint on the real answering pipeline.

Registered by ``app.main`` only when ``APP_ENV=staging``. In production none of these
routes exist (they return 404), and nothing here is imported.

It calls ``process_message`` -- the exact function the WhatsApp webhook calls -- so
there is no second AI engine. It never sends anything to WhatsApp.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from collections import deque
from threading import Lock
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from app.config import (
    ADMIN_PASSWORD,
    OPENAI_API_KEY,
    SECRET_KEY,
    WHATSAPP_ACCESS_TOKEN,
)
from app.engine_config import clear_pin
from app.engines.pipeline import process_message
from app.faq_admin import is_faq_admin
from app.guided_state import clear_session, set_session
from app.observability.privacy import phone_hash

MAX_TEXT_CHARS = 1000
try:
    MAX_MESSAGES_PER_HOUR = max(1, int(os.getenv("TEST_CHAT_MAX_PER_HOUR", "120")))
except ValueError:
    MAX_MESSAGES_PER_HOUR = 120

# Fictional numbers (555-01xx is reserved for fiction). Identity = phone number, which
# is also the key for guided sessions, engine pinning and FAQ-admin permission.
PERSONAS: dict[str, dict[str, str]] = {
    "parent_a": {"label": "Parent A (regular parent)", "phone": "15550100001"},
    "parent_b": {"label": "Parent B (second parent)", "phone": "15550100002"},
    "faq_admin": {"label": "FAQ admin (can use /faq)", "phone": "15550100003"},
}

_lock = Lock()
_recent: deque[float] = deque()


class ChatRequest(BaseModel):
    text: str = Field(..., min_length=1)
    persona: str = "parent_a"
    message_type: str = "text"  # "interactive" when a choice button was tapped


class ResetRequest(BaseModel):
    persona: str = "parent_a"


def redact(text: str | None) -> str | None:
    """Remove secrets from anything shown in debug output."""
    if not text:
        return text
    out = str(text)
    for secret in (OPENAI_API_KEY, ADMIN_PASSWORD, SECRET_KEY, WHATSAPP_ACCESS_TOKEN):
        if secret and len(secret) >= 6:
            out = out.replace(secret, "[redacted]")
    return re.sub(r"sk-[A-Za-z0-9_\-]{6,}", "sk-[redacted]", out)


def _allow_message() -> bool:
    now = time.time()
    with _lock:
        while _recent and now - _recent[0] > 3600:
            _recent.popleft()
        if len(_recent) >= MAX_MESSAGES_PER_HOUR:
            return False
        _recent.append(now)
        return True


def _persona_phone(persona: str) -> str | None:
    info = PERSONAS.get(persona)
    return info["phone"] if info else None


def _persona_view() -> list[dict[str, Any]]:
    return [
        {
            "id": pid,
            "label": info["label"],
            "phone_hash": phone_hash(info["phone"]),
            "faq_admin": is_faq_admin(info["phone"]),
        }
        for pid, info in PERSONAS.items()
    ]


def reset_conversation(phone: str) -> None:
    """Forget guided session, engine pin and any pending calendar question."""
    clear_session(phone)
    clear_pin(phone)
    set_session(f"calpick:{phone}", None)


def run_chat_turn(persona: str, text: str, message_type: str = "text") -> dict[str, Any]:
    """One turn through the shared WhatsApp pipeline, as a JSON-able dict."""
    phone = _persona_phone(persona)
    if phone is None:
        raise KeyError(persona)
    mtype = "interactive" if message_type == "interactive" else "text"
    result = process_message(
        phone=phone,
        text=text,
        message_id=f"test-chat-{uuid.uuid4()}",
        message_type=mtype,
        channel="test_chat",
    )
    usage = result.model_usage
    return {
        "ok": True,
        "persona": persona,
        "phone_hash": phone_hash(phone),
        "messages": [redact(m) for m in (result.messages or [])],
        "choices": result.choices,
        "route": result.route,
        "engine_id": result.engine_id,
        "engine_version": result.engine_version,
        "intent": result.intent,
        "flow_id": result.flow_id,
        "step_id": result.step_id,
        "state_transition": result.state_transition,
        "faq_id": result.faq_id,
        "faq_match_score": result.faq_match_score,
        "answer_confidence": result.answer_confidence,
        "retrieval_mode": result.retrieval_mode,
        "source_name": result.source_name,
        "source_url": result.source_url,
        "sources": list(result.sources or []),
        "answer_outcome": result.answer_outcome,
        "fallback": result.fallback,
        "error": redact(result.error),
        "latency_ms": result.latency_ms,
        "trace_id": result.trace_id,
        "model": {
            "model": usage.model,
            "llm_invocations": usage.invocations,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "estimated_cost_usd": usage.estimated_cost_usd,
        },
        # No agent/tool layer exists yet; this field is the stable place for it.
        "tools": [],
    }


def register_test_chat(
    app: Any,
    *,
    is_logged_in: Callable[[Request], bool],
    templates: Any,
    branding: Callable[[], dict[str, str]],
) -> None:
    @app.get("/admin/test-chat", response_class=HTMLResponse)
    async def test_chat_page(request: Request) -> Response:
        if not is_logged_in(request):
            return RedirectResponse(url="/admin", status_code=303)
        return templates.TemplateResponse(
            request,
            "admin_test_chat.html",
            {**branding(), "personas": _persona_view()},
        )

    @app.post("/admin/test-chat/api/message")
    async def test_chat_message(request: Request, body: ChatRequest) -> Response:
        if not is_logged_in(request):
            return JSONResponse({"ok": False, "error": "login required"}, status_code=401)
        text = body.text.strip()
        if not text or len(text) > MAX_TEXT_CHARS:
            return JSONResponse(
                {"ok": False, "error": f"text must be 1-{MAX_TEXT_CHARS} characters"},
                status_code=400,
            )
        if body.persona not in PERSONAS:
            return JSONResponse({"ok": False, "error": "unknown persona"}, status_code=400)
        if not _allow_message():
            return JSONResponse(
                {"ok": False, "error": "hourly Test Chat limit reached"}, status_code=429
            )
        try:
            return JSONResponse(run_chat_turn(body.persona, text, body.message_type))
        except Exception:
            return JSONResponse({"ok": False, "error": "internal error"}, status_code=500)

    @app.post("/admin/test-chat/api/reset")
    async def test_chat_reset(request: Request, body: ResetRequest) -> Response:
        if not is_logged_in(request):
            return JSONResponse({"ok": False, "error": "login required"}, status_code=401)
        phone = _persona_phone(body.persona)
        if phone is None:
            return JSONResponse({"ok": False, "error": "unknown persona"}, status_code=400)
        reset_conversation(phone)
        return JSONResponse({"ok": True, "persona": body.persona})

    @app.get("/admin/test-chat/api/personas")
    async def test_chat_personas(request: Request) -> Response:
        if not is_logged_in(request):
            return JSONResponse({"ok": False, "error": "login required"}, status_code=401)
        return JSONResponse({"ok": True, "personas": _persona_view()})
