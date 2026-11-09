"""Structured guided conversation engine (no agent framework)."""

from __future__ import annotations

import re
from typing import Any

from app.guided_metrics import record_guided_start, record_resolution
from app.guided_state import clear_session, get_session, set_session
from app.guided_store import get_topic

RESOLUTION_STEP = "__resolution__"
PARTIAL_STEP = "__partial_followup__"
UNRESOLVED_CONFIRM_STEP = "__unresolved_confirm__"

RESOLUTION_PROMPT = "Did this help you resolve your issue?"
RESOLUTION_CHOICES = [
    {"id": "resolved", "label": "Yes, resolved"},
    {"id": "partial", "label": "Partially"},
    {"id": "unresolved", "label": "Still need help"},
]

UNRESOLVED_CONFIRM_CHOICES = [
    {"id": "yes_contact", "label": "Yes, contact tips"},
    {"id": "no_thanks", "label": "No thanks"},
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


def _present_step(
    phone: str,
    topic: dict[str, Any],
    session: dict[str, Any],
    step_id: str,
) -> dict[str, Any]:
    step = topic["steps"][step_id]
    session["step_id"] = step_id
    if step.get("recommend_human"):
        session["human_recommended"] = True
    set_session(phone, session)
    choices = step.get("choices") or []
    messages = [format_step_message(step.get("prompt") or "", choices)]
    if step.get("end") and step.get("ask_resolution"):
        follow = _resolution_response(phone, topic, session)
        return {
            "messages": [messages[0], follow["messages"][0]],
            "choices": follow.get("choices"),
            "ended": False,
            "topic_id": topic["id"],
            "step_id": RESOLUTION_STEP,
        }
    return {
        "messages": messages,
        "choices": choices or None,
        "ended": False,
        "topic_id": topic["id"],
        "step_id": step_id,
    }


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
    session = {
        "topic_id": topic_id,
        "step_id": start,
        "human_recommended": False,
    }
    set_session(phone, session)
    record_guided_start(topic_id)
    return _present_step(phone, topic, session, start)


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


def _lookup_deadline(topic: dict[str, Any], text: str) -> str:
    cleaned = (text or "").strip().lower()
    deadlines = topic.get("deadlines") or {}
    if not isinstance(deadlines, dict):
        deadlines = {}
    for key, value in deadlines.items():
        if str(key).lower() in cleaned or cleaned in str(key).lower():
            return str(value)
    return (
        "I don't have a confirmed deadline for that event. "
        "Please check the latest PTSA announcement or contact the organizer."
    )


def _try_faq_for_partial(text: str) -> str | None:
    try:
        from app.faq_service import answer_faq_question

        answer = (answer_faq_question(text) or "").strip()
    except Exception:
        return None
    if not answer:
        return None
    lowered = answer.lower()
    if lowered.startswith("i couldn't find") or lowered.startswith("sorry,"):
        return None
    return answer


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
        set_session(phone, session)
        return {
            "messages": [
                "Thanks for letting me know. What part do you still need help with? "
                "(Short reply is fine — no student names needed.)"
            ],
            "choices": None,
            "ended": False,
        }

    if outcome == "unresolved":
        session["step_id"] = UNRESOLVED_CONFIRM_STEP
        set_session(phone, session)
        return {
            "messages": [
                format_step_message(
                    "I'm sorry this didn't resolve your issue. "
                    "Would you like guidance on contacting the school office or an organizer?",
                    UNRESOLVED_CONFIRM_CHOICES,
                )
            ],
            "choices": UNRESOLVED_CONFIRM_CHOICES,
            "ended": False,
        }

    record_resolution(topic["id"], "resolved", human_recommended=human)
    clear_session(phone)
    return {
        "messages": ["Great! Glad I could help."],
        "choices": None,
        "ended": True,
    }


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
                "Guided topics: Lost & Found, Conferences, Spiritwear, "
                "Clubs, PTSA events.\n"
                "Describe your situation, or ask a direct FAQ question. "
                "Send cancel anytime during a guided chat to leave it."
            ],
            "choices": None,
            "ended": True,
        }

    topic = get_topic(session["topic_id"])
    if not topic:
        clear_session(phone)
        return {
            "messages": [
                "That topic is no longer available. Ask your question and I'll use the FAQ."
            ],
            "choices": None,
            "ended": True,
        }

    step_id = session.get("step_id") or ""
    if step_id == RESOLUTION_STEP:
        return _handle_resolution(phone, topic, session, text)

    if step_id == UNRESOLVED_CONFIRM_STEP:
        choice = _match_choice(text, UNRESOLVED_CONFIRM_CHOICES)
        human = bool(session.get("human_recommended"))
        record_resolution(topic["id"], "unresolved", human_recommended=human)
        clear_session(phone)
        if choice and choice["id"] == "yes_contact":
            escalation = topic.get("escalation") or (
                "Please contact the school office or the appropriate organizer for next steps."
            )
            return {
                "messages": [
                    f"{escalation}\n\n"
                    "I cannot contact staff for you or invent school policy."
                ],
                "choices": None,
                "ended": True,
            }
        return {
            "messages": ["Okay. Message anytime with another question."],
            "choices": None,
            "ended": True,
        }

    if step_id == PARTIAL_STEP:
        human = bool(session.get("human_recommended"))
        faq_help = _try_faq_for_partial(text)
        record_resolution(topic["id"], "partial", human_recommended=human)
        clear_session(phone)
        if faq_help:
            return {
                "messages": [
                    "Here's related info from the approved FAQ:\n\n"
                    f"{faq_help}\n\n"
                    "If that still doesn't cover it, please contact the school office "
                    "or organizer. I cannot contact them for you."
                ],
                "choices": None,
                "ended": True,
            }
        escalation = topic.get("escalation") or (
            "Please contact the school office or organizer for what remains."
        )
        return {
            "messages": [
                "Thanks — I couldn't fully resolve that from the approved knowledge base.\n\n"
                f"{escalation}"
            ],
            "choices": None,
            "ended": True,
        }

    step = (topic.get("steps") or {}).get(step_id) or {}
    if step.get("await_text"):
        handler = step.get("handler")
        if handler == "deadline_lookup":
            answer = _lookup_deadline(topic, text)
            # Move to a synthetic end then ask resolution.
            session["human_recommended"] = session.get("human_recommended", False)
            set_session(phone, session)
            follow = _resolution_response(phone, topic, session)
            return {
                "messages": [answer, follow["messages"][0]],
                "choices": follow.get("choices"),
                "ended": False,
                "topic_id": topic["id"],
                "step_id": RESOLUTION_STEP,
            }
        clear_session(phone)
        return {
            "messages": ["Thanks. Ask another question anytime."],
            "choices": None,
            "ended": True,
        }

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
        return _present_step(phone, topic, session, next_id)

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
    # Situation language should still prefer guided flows.
    if re.search(
        r"\b(lost (my|his|her|their|a|something)|can't find|cant find|"
        r"left on the bus|order is wrong|hasn't arrived|hasnt arrived|"
        r"want to volunteer|help with conferences|can't schedule|cant schedule)\b",
        cleaned,
    ):
        return False
    return bool(
        re.search(
            r"\b(where is|where are|how much|when is|when are|can (my child|students|parents)|"
            r"is (there )?school|what time|what day|how do i (register|order|schedule|submit)|"
            r"where (can|do|should) i|where do i)\b",
            cleaned,
        )
    )


def preview_topic(topic_id: str, choices_path: list[str] | None = None) -> list[str]:
    """Offline walkthrough for admin preview (does not touch WhatsApp state)."""
    topic = get_topic(topic_id)
    if not topic:
        return ["Topic not found."]
    lines = [f"Preview: {topic.get('title') or topic_id}"]
    step_id = topic["start_step"]
    path = list(choices_path or [])
    path_i = 0
    guard = 0
    while step_id and guard < 20:
        guard += 1
        step = topic["steps"].get(step_id) or {}
        choices = step.get("choices") or []
        lines.append(format_step_message(step.get("prompt") or "", choices))
        if step.get("await_text"):
            lines.append("(Parent types a free-text reply here.)")
            if step.get("handler") == "deadline_lookup":
                sample = path[path_i] if path_i < len(path) else "Color Run"
                lines.append(_lookup_deadline(topic, sample))
                lines.append(format_step_message(RESOLUTION_PROMPT, RESOLUTION_CHOICES))
            break
        if step.get("end"):
            if step.get("ask_resolution"):
                lines.append(format_step_message(RESOLUTION_PROMPT, RESOLUTION_CHOICES))
            break
        if not choices:
            break
        if path_i < len(path):
            matched = _match_choice(path[path_i], choices)
            path_i += 1
        else:
            matched = choices[0]
        if not matched:
            break
        step_id = matched.get("next")
    return lines
