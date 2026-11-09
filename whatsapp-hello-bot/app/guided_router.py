"""Route inbound parent messages to FAQ, guided flow, or human handoff."""

from __future__ import annotations

import re
from typing import Any

from app.guided_engine import looks_like_direct_faq, start_topic
from app.guided_state import get_session
from app.guided_store import list_topics

HUMAN_PATTERNS = (
    r"\bsecurity\b",
    r"\bworthwhile\b",
    r"\bworth it\b",
    r"\bdisputed?\b",
    r"\banother student\b",
    r"\bsomeone else'?s child\b",
    r"\bpersonal situation\b",
    r"\bbully",
    r"\bharass",
)


HUMAN_REPLY = (
    "That's something I shouldn't handle in this chat.\n\n"
    "Please contact the school office, your child's teacher, or a PTSA organizer "
    "directly. I only share administrator-approved FAQ and guided steps, and "
    "I cannot contact staff for you or invent school policy."
)


def _score_topic(text: str, topic: dict[str, Any]) -> int:
    cleaned = text.lower()
    score = 0
    for trigger in topic.get("triggers") or []:
        t = str(trigger).lower().strip()
        if t and t in cleaned:
            score += max(1, len(t.split()))
    return score


def match_guided_topic(text: str) -> dict[str, Any] | None:
    best = None
    best_score = 0
    for topic in list_topics(enabled_only=True):
        score = _score_topic(text, topic)
        if score > best_score:
            best = topic
            best_score = score
    if best_score <= 0:
        return None
    return best


def needs_human(text: str) -> bool:
    cleaned = (text or "").lower()
    return any(re.search(pat, cleaned) for pat in HUMAN_PATTERNS)


def route_message(phone: str, text: str) -> dict[str, Any]:
    """Return a routing decision for a new (non-session) message.

    Kinds: continue_guided | start_guided | faq | human
    """
    if get_session(phone):
        return {"kind": "continue_guided"}

    if needs_human(text):
        return {"kind": "human", "reply": HUMAN_REPLY}

    # Prefer Mode A for clear factual prompts.
    if looks_like_direct_faq(text):
        return {"kind": "faq"}

    topic = match_guided_topic(text)
    if topic:
        return {"kind": "start_guided", "topic_id": topic["id"]}

    return {"kind": "faq"}


def begin_guided(phone: str, topic_id: str) -> dict[str, Any]:
    return start_topic(phone, topic_id)
