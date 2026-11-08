"""Exercise 04: tiny agent router (no LLM, no WhatsApp network)."""

from __future__ import annotations

import re
from typing import Any


def is_help_command(text: str) -> bool:
    cleaned = (text or "").strip().lower()
    return cleaned in {"help", "/help", "menu", "/menu", "start"}


def is_opener_message(text: str) -> bool:
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return True
    if cleaned in {"hi", "hello", "hey"}:
        return True
    return cleaned.startswith("i have a question about") or cleaned.startswith(
        "hi, i have a question about"
    )


def is_faq_command(text: str) -> bool:
    return (text or "").strip().lower().startswith("/faq")


def parse_faq_command(text: str) -> tuple[str, str] | None:
    """Parse '/faq Q: ... A: ...' into (question, answer) or None."""
    # TODO: implement a simple parse; production supports multiline too
    raise NotImplementedError


def route_message(text: str, *, sender_is_admin: bool = False) -> dict[str, Any]:
    """Choose the next action for an inbound WhatsApp text.

    Order matters — match production:
      help -> greeting/opener -> /faq -> faq_answer
    """
    # TODO: implement routing using the helpers above
    # For /faq:
    #   - if not sender_is_admin => {"action": "faq_admin_denied"}
    #   - if parse fails => {"action": "faq_admin_usage"}
    #   - else => {"action": "faq_admin", "question": q, "answer": a}
    raise NotImplementedError
