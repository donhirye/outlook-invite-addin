"""Structured guided conversation engine (no agent framework)."""

from __future__ import annotations

import re
from typing import Any

from app.guided_metrics import record_guided_start, record_resolution
from app.guided_state import clear_session, get_session, set_session
from app.guided_store import get_topic

RESOLUTION_STEP = "__resolution__"
PARTIAL_STEP = "__partial_followup__"

RESOLUTION_PROMPT = "Did this help you resolve your issue?"
RESOLUTION_CHOICES = [
    {"id": "resolved", "label": "Yes, resolved"},
    {"id": "partial", "label": "Partially"},
    {"id": "unresolved", "label": "Still need help"},
]

CANCEL_WORDS = {"cancel", "stop", "quit", "nevermind", "never mind", "end"}
RESTART_WORDS = {"restart", "start over", "reset"}
MENU_WORDS = {"menu", "topics", "guided"}


def is_guided_control(text: str) -> str | None:
    cleaned = (text or "").strip().lower()
    if cleaned in CANCEL_WORDS:
        return "cancel"
    if cleaned in RESTART_WORDS:
        return "restart"
    if cleaned in MENU_WORDS:
        return "menu"
    return None


def _choice_lines(choices: list[dict[str, str]]) -> str:
    lines = []
    for idx, choice in enumerate(choices, start=1):
        lines.append(f"{idx}. {choice['label']}")
    return "\n".join(lines)


def format_step_message(prompt: str, choices: list[dict[str, str]] | None = None) -> str:
    text = (prompt or "").strip()
    if choices:
        text = f"{text}\n\n{_choice_lines(choices)}\n\nReply with a number or the option text."
    return text


def _match_choice(text: str, choices: list[dict[str, str]]) -> dict[str, str] | None:
    cleaned = (text or "").strip().lower()
    if not cleaned or not choices:
        return None
    if cleaned.isdigit():
        idx = int(cleaned) - 1
        if 0 <= idx < len(choices):
            return choices[idx]
    for choice in choices:
        label = (choice.get("label") or "").strip().lower()
        cid = (choice.get("id") or "").strip().lower()
        if cleaned == cid or cleaned == label:
            return choice
        if label and (cleaned in label or label in cleaned):
            return choice
    return None


def start_topic(phone: str, topic_id: str) -> dict[str, Any]:
    topic = get_topic(topic_id)
    if not topic or not topic.get("enabled", True):
        return {
            "messages": [
                "That guided topic is not available right now. Ask your question and I'll try the FAQ."
            ],
            "choices": None,
            "ended": True,
        }
    start = topic["start_step"]
    step = topic["steps"][start]
    choices = step.get("choices") or []
    session = {
        "topic_id": topic_id,
        "step_id": start,
        "human_recommended": False,
    }
    set_session(phone, session)
    record_guided_start(topic_id)
    return {
        "messages": [format_step_message(step.get("prompt") or "", choices)],
        "choices": choices or None,
        "ended": False,
        "topic_id": topic_id,
        "step_id": start,
    }


def _resolution_response(phone: str, topic: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    session["step_id"] = RESOLUTION_STEP
    set_session(phone, session)
    return {
        "messages": [format_step_message(RESOLUTION_PROMPT, RESOLUTION_CHOICES)],
        "choices": RESOLUTION_CHOICES,
        "ended": False,
        "topic_id": topic["id"],
        "step_id": RESOLUTION_STEP,
    }


def _handle_resolution(
    phone: str,
    topic: dict[str, Any],
    session: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    choice = _match_choice(text, RESOLUTION_CHOICES)
    if not choice:
        return {
            "messages": [
                format_step_message(
                    "Please choose one:\n" + RESOLUTION_PROMPT,
                    RESOLUTION_CHOICES,
                )
            ],
            "choices": RESOLUTION_CHOICES,
            "ended": False,
        }

    outcome = choice["id"]
    human = bool(session.get("human_recommended"))
    if outcome == "partial":
        session["step_id"] = PARTIAL_STEP
        session["pending_outcome"] = "partial"
        set_session(phone, session)
        return {
            "messages": [
                "What part is still unresolved? Reply in a short sentence "
                "(no student names needed)."
            ],
            "choices": None,
            "ended": False,
        }

    record_resolution(topic["id"], outcome, human_recommended=human)
    clear_session(phone)
    if outcome == "resolved":
        msg = "Glad that helped. Message anytime with another question."
    else:
        escalation = topic.get("escalation") or (
            "Please contact the school office or the appropriate organizer for next steps."
        )
        msg = (
            "I'm sorry it hasn't been resolved.\n\n"
            f"{escalation}\n\n"
            "You can also ask another question here anytime."
        )
    return {"messages": [msg], "choices": None, "ended": True}


def advance(phone: str, text: str) -> dict[str, Any]:
    session = get_session(phone)
    if not session:
        return {
            "messages": ["No guided conversation is active. Ask a question anytime."],
            "choices": None,
            "ended": True,
        }

    control = is_guided_control(text)
    if control == "cancel":
        clear_session(phone)
        return {
            "messages": ["Okay — guided help canceled. Ask a new question anytime."],
            "choices": None,
            "ended": True,
        }
    if control == "restart":
        return start_topic(phone, session["topic_id"])
    if control == "menu":
        clear_session(phone)
        return {
            "messages": [
                "Guided topics: Lost & Found, Conferences, Spiritwear.\n"
                "Describe your situation, or ask a direct FAQ question."
            ],
            "choices": None,
            "ended": True,
        }

    topic = get_topic(session["topic_id"])
    if not topic:
        clear_session(phone)
        return {
            "messages": ["That topic is no longer available. Ask your question and I'll use the FAQ."],
            "choices": None,
            "ended": True,
        }

    step_id = session.get("step_id") or ""
    if step_id == RESOLUTION_STEP:
        return _handle_resolution(phone, topic, session, text)
    if step_id == PARTIAL_STEP:
        # Intentionally do not store free-text details — only the outcome.
        record_resolution(
            topic["id"],
            "partial",
            human_recommended=bool(session.get("human_recommended")),
        )
        clear_session(phone)
        escalation = topic.get("escalation") or (
            "Please contact the school office or organizer for what remains."
        )
        return {
            "messages": [
                "Thanks — noted that it's only partly resolved.\n\n"
                f"{escalation}"
            ],
            "choices": None,
            "ended": True,
        }

    step = (topic.get("steps") or {}).get(step_id) or {}
    choices = step.get("choices") or []
    if choices:
        matched = _match_choice(text, choices)
        if not matched:
            return {
                "messages": [
                    format_step_message(
                        "I didn't catch that. Please choose one option:",
                        choices,
                    )
                ],
                "choices": choices,
                "ended": False,
            }
        next_id = matched.get("next")
        if not next_id or next_id not in topic["steps"]:
            clear_session(phone)
            return {
                "messages": ["Thanks. Ask another question anytime."],
                "choices": None,
                "ended": True,
            }
        next_step = topic["steps"][next_id]
        session["step_id"] = next_id
        if next_step.get("recommend_human"):
            session["human_recommended"] = True
        set_session(phone, session)
        next_choices = next_step.get("choices") or []
        messages = [
            format_step_message(next_step.get("prompt") or "", next_choices)
        ]
        if next_step.get("end") and next_step.get("ask_resolution"):
            follow = _resolution_response(phone, topic, session)
            # Send answer first, then resolution question as separate message.
            return {
                "messages": [messages[0], follow["messages"][0]],
                "choices": follow.get("choices"),
                "ended": False,
                "topic_id": topic["id"],
                "step_id": RESOLUTION_STEP,
            }
        return {
            "messages": messages,
            "choices": next_choices or None,
            "ended": False,
            "topic_id": topic["id"],
            "step_id": next_id,
        }

    # Leaf without choices (shouldn't normally be entered via advance)
    if step.get("ask_resolution"):
        return _resolution_response(phone, topic, session)
    clear_session(phone)
    return {
        "messages": [(step.get("prompt") or "Okay.").strip()],
        "choices": None,
        "ended": True,
    }


def looks_like_direct_faq(text: str) -> bool:
    cleaned = (text or "").strip().lower()
    return bool(
        re.search(
            r"\b(where is|where are|how much|when is|when are|can students|can parents|"
            r"is school closed|what time|what day)\b",
            cleaned,
        )
    )
