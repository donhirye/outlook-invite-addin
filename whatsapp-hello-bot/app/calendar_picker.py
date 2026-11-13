"""'Show me the calendar' flow.

Ask which calendar the parent wants (SD 204, PTSA events, or both), remember the
question for a few minutes, then list that calendar's upcoming events.
"""

from __future__ import annotations

import re
import time
from datetime import date
from typing import Any

from app.calendar_service import (
    _collect_sources,
    _mentioned_months,
    _source_footer,
    is_faq_action_question,
)
from app.calendar_store import DEFAULT_SOURCE_NAME, list_events, parse_iso_date
from app.faq_records import chicago_today
from app.guided_state import get_session, set_session

PENDING_TTL_SECONDS = 10 * 60
ID_PREFIX = "calpick:"
BOTH_KEY = "both"
MAX_BODY_CHARS = 3500

_SHOW_PATTERNS = (
    r"\b(show|see|view|send|share|list|get|give|display|pull up)\b.{0,25}\bcalendars?\b",
    r"\bwhat(?:'s|s| is| are)?\s+(?:on|in)\s+the\s+(?:school\s+)?calendars?\b",
    r"\bwhat\s+calendars?\b",
    r"\bcalendars?\s+(?:do you have|available)\b",
    r"^\s*(?:the\s+|your\s+|our\s+)?(?:school\s+|full\s+)?calendars?\s*[?!.]*\s*$",
)
# Not a "show me the list" request: wants a link/file, a sync, or one specific answer.
_NOT_SHOW_RE = re.compile(
    r"\b(link|url|pdf|ics|download|sync|subscribe|google|outlook|apple|iphone|"
    r"print|add (?:it )?to|when|next|today|tomorrow|this week)\b"
)

_LABEL_DESCRIPTIONS = {
    "SD 204 calendar": "district holidays, breaks and no-school days",
    "PTSA events calendar": "Crone PTSA meetings, socials and school events",
}
_FILLER = {
    "the", "calendar", "calendars", "please", "one", "show", "me", "i", "want",
    "would", "like", "see", "pick", "choose", "option", "number", "and", "only",
    "just", "a", "to", "of", "ok", "okay", "let", "s", "lets", "for", "my", "can",
    "you", "school",
}
_BOTH_WORDS = {"both", "all", "each", "everything", "either"}
_ORDINALS = {"first": 1, "second": 2, "third": 3}
_KEYWORD_STOP = {
    "calendar", "school", "of", "the", "2026", "2027", "important", "dates",
    "middle", "indian", "prairie", "1", "2",
}


def is_show_calendar_question(text: str) -> bool:
    cleaned = (text or "").lower().strip()
    if not cleaned or is_faq_action_question(cleaned):
        return False
    if _NOT_SHOW_RE.search(cleaned) or _mentioned_months(cleaned):
        return False
    return any(re.search(pat, cleaned) for pat in _SHOW_PATTERNS)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "calendar"


def _short_label(name: str) -> str:
    lowered = name.lower()
    if "204" in lowered and "district" in lowered:
        return "SD 204 calendar"
    if "crone" in lowered or "ptsa" in lowered:
        return "PTSA events calendar"
    return name[:20].rstrip()


def calendar_options() -> list[dict[str, Any]]:
    """One option per calendar that has events (District 204 first)."""
    by_name: dict[str, list[dict[str, Any]]] = {}
    for ev in list_events():
        name = (ev.get("calendar_name") or "").strip() or DEFAULT_SOURCE_NAME
        by_name.setdefault(name, []).append(ev)
    options: list[dict[str, Any]] = []
    for name, events in by_name.items():
        label = _short_label(name)
        words = set(re.findall(r"[a-z0-9]+", f"{name} {label}".lower())) - _KEYWORD_STOP
        if "204" in words:
            words |= {"sd204", "d204"}
        if "ptsa" in words:
            words.add("pta")
        options.append(
            {
                "key": _slug(name),
                "name": name,
                "label": label,
                "keywords": words,
                "events": events,
            }
        )
    options.sort(key=lambda o: ("district" not in o["name"].lower(), o["name"]))
    return options


def _state_key(phone: str) -> str:
    return f"calpick:{(phone or '').strip()}"


def _short_day(day: date, *, year: bool) -> str:
    text = f"{day.strftime('%a, %b')} {day.day}"
    return f"{text}, {day.year}" if year else text


def _when(ev: dict[str, Any]) -> str:
    start = parse_iso_date(ev.get("start_date") or "")
    end = parse_iso_date(ev.get("end_date") or "") or start
    if not start or not end:
        return str(ev.get("start_date") or "")
    if start == end:
        return _short_day(start, year=True)
    if start.year == end.year:
        return f"{_short_day(start, year=False)} – {_short_day(end, year=True)}"
    return f"{_short_day(start, year=True)} – {_short_day(end, year=True)}"


def _event_line(ev: dict[str, Any]) -> str:
    notes = (ev.get("notes") or "").strip()
    notes_part = f" ({notes})" if notes else ""
    no_school = "no school" in (ev.get("student_attendance") or "").lower()
    suffix = " — no school" if no_school else ""
    return f"• {_when(ev)}: {ev.get('name')}{notes_part}{suffix}"


def render_calendar(option: dict[str, Any], today: date) -> str:
    """Upcoming events for one calendar, with that calendar's own source."""
    upcoming = []
    for ev in option["events"]:
        start = parse_iso_date(ev.get("start_date") or "")
        end = parse_iso_date(ev.get("end_date") or "") or start
        if start and end and end >= today:
            upcoming.append((start, ev.get("name") or "", ev))
    upcoming.sort(key=lambda item: (item[0], item[1]))
    footer = _source_footer(_collect_sources(option["events"]))
    header = f"*{option['name']}*"
    if not upcoming:
        return f"{header}\nNo upcoming dates are listed on this calendar.\n\n{footer}"
    lines = [_event_line(ev) for _, _, ev in upcoming]
    shown: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) > MAX_BODY_CHARS:
            break
        shown.append(line)
        size += len(line) + 1
    if len(shown) < len(lines):
        shown.append(f"…and {len(lines) - len(shown)} more later in the year.")
    return f"{header}\nUpcoming dates:\n" + "\n".join(shown) + f"\n\n{footer}"


def _question_body(options: list[dict[str, Any]]) -> str:
    lines = [f"I have {len(options)} calendars:"]
    for idx, option in enumerate(options, start=1):
        desc = _LABEL_DESCRIPTIONS.get(option["label"])
        lines.append(f"{idx}. {option['label']}" + (f" — {desc}" if desc else ""))
    lines.append(f"{len(options) + 1}. Both")
    lines.append(
        f"\nWhich one would you like to see? Tap a button or reply "
        f"1-{len(options) + 1}."
    )
    return "\n".join(lines)


def start_calendar_picker(phone: str, today: date | None = None) -> dict[str, Any] | None:
    """Ask which calendar to show. Lists directly when there is only one."""
    today = today or chicago_today()
    options = calendar_options()
    if not options:
        return None
    if len(options) == 1:
        return {"messages": [render_calendar(options[0], today)], "choices": None}
    set_session(
        _state_key(phone),
        {"keys": [o["key"] for o in options], "asked_at": time.time()},
    )
    choices = [{"id": f"{ID_PREFIX}{o['key']}", "label": o["label"]} for o in options]
    choices.append({"id": f"{ID_PREFIX}{BOTH_KEY}", "label": "Both"})
    return {"messages": [_question_body(options)], "choices": choices}


def _parse_choice(text: str, options: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Selected options for a reply, or None if the reply is not an answer."""
    cleaned = (text or "").lower().strip()
    if cleaned.startswith(ID_PREFIX):
        key = cleaned[len(ID_PREFIX):]
        if key == BOTH_KEY:
            return list(options)
        picked = [o for o in options if o["key"] == key]
        return picked or None
    tokens = [t for t in re.findall(r"[a-z0-9]+", cleaned) if t not in _FILLER]
    if not tokens:
        return None
    both_index = len(options) + 1
    chosen: set[int] = set()
    for token in tokens:
        if token in _BOTH_WORDS:
            chosen.update(range(len(options)))
            continue
        hits = [i for i, o in enumerate(options) if token in o["keywords"]]
        if hits:  # checked before numbers: "204" is a name, not option 204
            chosen.update(hits)
            continue
        number = int(token) if token.isdigit() else _ORDINALS.get(token)
        if number is None:
            return None  # an unrelated word: this is a new question, not an answer
        if number == both_index:
            chosen.update(range(len(options)))
        elif 1 <= number <= len(options):
            chosen.add(number - 1)
        else:
            return None
    return [options[i] for i in sorted(chosen)] or None


def resolve_calendar_pick(
    phone: str, text: str, today: date | None = None
) -> dict[str, Any] | None:
    """If we asked which calendar, answer it. Any other reply drops the question."""
    state = get_session(_state_key(phone))
    if not state:
        return None
    set_session(_state_key(phone), None)  # one shot: answered or dropped
    if time.time() - float(state.get("asked_at") or 0) > PENDING_TTL_SECONDS:
        return None
    wanted = set(state.get("keys") or [])
    options = [o for o in calendar_options() if o["key"] in wanted]
    if not options:
        return None
    selected = _parse_choice(text, options)
    if not selected:
        return None
    today = today or chicago_today()
    return {"messages": [render_calendar(o, today) for o in selected]}
