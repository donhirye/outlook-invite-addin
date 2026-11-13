"""Deterministic school-calendar answering (America/Chicago)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from app.calendar_store import (
    DEFAULT_SOURCE_NAME,
    DEFAULT_SOURCE_URL,
    get_calendar_meta,
    list_events,
    parse_iso_date,
)
from app.faq_records import chicago_today

CALENDAR_PATTERNS = (
    r"\bis there school\b",
    r"\bschool (today|tomorrow)\b",
    r"\b(next|upcoming)\s+(school\s+)?(holiday|break)\b",
    r"\b(thanksgiving|winter|spring)\s+break\b",
    r"\bhow many days until\b",
    r"\b(last|first)\s+day of school\b",
    r"\bwhen does school start\b",
    r"\bno school\b",
    r"\bschool holiday\b",
    r"\binstitute day\b",
    r"\bparent[\s/-]*teacher\s+conference",
    # Broader parent phrasing → school calendar (not FAQ).
    r"\b(time|days?)\s+off\b",
    r"\b(days?\s+off|off\s+from\s+school|school\s+off)\b",
    r"\b(holiday|break|vacation)s?\b.*\bschool\b|\bschool\b.*\b(holiday|break|vacation)s?\b",
    r"\bwinter\b.*\b(break|holiday|off|school)\b|\b(break|holiday|off)\b.*\bwinter\b",
    r"\b(december|january|february|march|april|may|june|july|august|september|october|november)\b.*\b(school|break|holiday|off)\b",
    r"\b(school|break|holiday|off)\b.*\b(december|january|february|march|april|may|june|july|august|september|october|november)\b",
    r"\bschool calendar\b|\bdistrict calendar\b",
    # Holiday-season wording (Christmas / New Year / "the holidays").
    r"\bchristmas\b",
    r"\bnew\s*year'?s?\b",
    r"\baround the holidays\b|\b(the\s+)?holidays\b.*\b(time off|days? off|break|off)\b",
    r"\b(time off|days? off|break|off)\b.*\b(the\s+)?holidays\b",
    r"\blong break\b",
)


# Action-style questions (register, cost, volunteer, how do I…) are answered by the
# FAQ, not the calendar. This guard keeps the calendar from stealing them.
_FAQ_ACTION_RE = re.compile(
    r"\b(regist\w*|sign(?:ing)?[\s-]?ups?|rsvp|costs?|fees?|prices?|how much|"
    r"volunteer\w*|donat\w*|tickets?|buy|purchase|"
    r"how (?:do|can|should|would) (?:i|we)|how to|"
    r"what (?:to bring|should (?:i|we) bring)|permission slips?)\b"
)
# Name-lookup path only: "where is …" is a location question for the FAQ.
_WHERE_RE = re.compile(r"\bwhere\b")
# A date/time cue is required before a bare event name is treated as a calendar question.
_TIME_CUE_RE = re.compile(
    r"\b(when|what\s+(?:day|date|time)|which\s+(?:day|date)|dates?|times?|"
    r"next|upcoming|schedule[d]?|starts?|begins?|held)\b"
)
# Break/holiday questions belong to the dedicated break branches, not name lookup.
_BREAK_WORD_RE = re.compile(r"\b(break|holiday|vacation)s?\b")

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "when", "what", "whats", "s",
    "of", "for", "on", "in", "at", "to", "and", "or", "do", "does", "did", "we",
    "you", "i", "my", "me", "our", "us", "there", "it", "this", "that", "next",
    "upcoming", "date", "dates", "time", "times", "with", "about", "will", "be",
    "have", "has", "any", "can", "tell", "please", "coming", "happening", "by",
    "which", "how", "long", "much", "many", "get", "from", "up", "out",
}
# Words too generic to identify an event on their own.
_WEAK = {
    "general", "meeting", "night", "day", "grade", "school", "event", "new",
    "district", "parent", "teacher", "first", "last",
}
_ALIASES = {
    "mtg": "meeting",
    "mtgs": "meeting",
    "pta": "ptsa",
    "festival": "fest",
    "conf": "conference",
    "confs": "conference",
}
_ORDINAL_RE = re.compile(r"^\d+(st|nd|rd|th)$")
_WEEKDAYS = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}
_IGNORE_IN_QUESTION = {
    "crone", "middle", "today", "tomorrow", "tonight", "week", "year", "morning",
    "afternoon", "evening", "mon", "tue", "wed", "thu", "fri",
}


def _stem(token: str) -> str:
    token = _ALIASES.get(token, token)
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    return _ALIASES.get(token, token)


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for raw in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if raw in _STOPWORDS:
            continue
        out.append(_stem(raw))
    return out


def find_events_by_name(text: str) -> list[dict[str, Any]]:
    """Events whose name is clearly referred to in the question (not break/holiday)."""
    cleaned = (text or "").lower()
    if _BREAK_WORD_RE.search(cleaned):
        return []
    q_set = set(_tokens(cleaned))
    q_ord = {t for t in q_set if _ORDINAL_RE.match(t)}
    ignore = set(_MONTH_NAME_TO_NUM) | _WEEKDAYS | _IGNORE_IN_QUESTION
    q_content = {
        t for t in q_set if t not in _WEAK and t not in q_ord and t not in ignore
    }
    if not q_content:
        return []
    matches: list[dict[str, Any]] = []
    for ev in list_events():
        e_set = set(_tokens(ev.get("name") or ""))
        e_ord = {t for t in e_set if _ORDINAL_RE.match(t)}
        strong = {t for t in e_set if t not in _WEAK and t not in e_ord}
        if not strong or not (strong & q_set):
            continue
        # "7th grade social" must not match the 6th grade one.
        if q_ord and e_ord and not (q_ord & e_ord):
            continue
        # Partial name match is only OK if every distinctive word asked is in the name
        # ("fall concert" must not match "Fall Fest").
        if not strong <= q_set and not q_content <= e_set:
            continue
        matches.append(ev)
    return matches


def looks_like_calendar_question(text: str) -> bool:
    cleaned = (text or "").lower()
    if _FAQ_ACTION_RE.search(cleaned):
        return False
    if any(re.search(pat, cleaned) for pat in CALENDAR_PATTERNS):
        return True
    if _WHERE_RE.search(cleaned) or not _TIME_CUE_RE.search(cleaned):
        return False
    return bool(find_events_by_name(cleaned))


def _event_source(ev: dict[str, Any]) -> tuple[str, str]:
    name = (ev.get("source_name") or "").strip() or DEFAULT_SOURCE_NAME
    url = (ev.get("source_url") or "").strip() or DEFAULT_SOURCE_URL
    return name, url


def _collect_sources(events: list[dict[str, Any]] | None) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []
    for ev in events or []:
        src = _event_source(ev)
        if src not in seen:
            seen.append(src)
    return seen


def _source_footer(sources: list[tuple[str, str]] | None = None) -> str:
    if not sources:
        meta = get_calendar_meta()
        sources = [
            (
                meta.get("source_name") or DEFAULT_SOURCE_NAME,
                meta.get("source_url") or DEFAULT_SOURCE_URL,
            )
        ]
    if len(sources) == 1:
        name, url = sources[0]
        return f"Source: {name}\n{url}"
    return "Sources:\n" + "\n".join(f"{name}\n{url}" for name, url in sources)


def format_calendar_answer(
    body: str, events: list[dict[str, Any]] | None = None
) -> str:
    """Wrap an answer with its source footer.

    With ``events`` the footer cites those events' own sources; without them it
    cites the calendar-wide source.
    """
    footer = _source_footer(_collect_sources(events))
    return f"*School calendar*\n{(body or '').strip()}\n\n{footer}"


def _result(body: str, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    sources = _collect_sources(events)
    if not sources:
        meta = get_calendar_meta()
        sources = [
            (
                meta.get("source_name") or DEFAULT_SOURCE_NAME,
                meta.get("source_url") or DEFAULT_SOURCE_URL,
            )
        ]
    return {
        "handled": True,
        "answer": format_calendar_answer(body, events),
        "source_name": sources[0][0],
        "source_url": sources[0][1],
    }


def _no_school_ranges() -> list[tuple[date, date, dict[str, Any]]]:
    ranges: list[tuple[date, date, dict[str, Any]]] = []
    for ev in list_events():
        attendance = (ev.get("student_attendance") or "").lower()
        if "no school" not in attendance:
            continue
        start = parse_iso_date(ev.get("start_date") or "")
        end = parse_iso_date(ev.get("end_date") or "") or start
        if start and end:
            ranges.append((start, end, ev))
    ranges.sort(key=lambda item: item[0])
    return ranges


def _covering_event(day: date) -> dict[str, Any] | None:
    for start, end, ev in _no_school_ranges():
        if start <= day <= end:
            return ev
    return None


def _is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def is_school_day(day: date) -> tuple[bool, str]:
    """Return (is_school_day, reason). Outside known year: uncertain."""
    if _is_weekend(day):
        return False, "weekend"
    ev = _covering_event(day)
    if ev:
        note = ""
        if "tentative" in (ev.get("notes") or "").lower() or "tentative" in (
            ev.get("name") or ""
        ).lower():
            note = " (listed as tentative on the district calendar)"
        return False, f"no school — {ev.get('name')}{note}"
    # School year window: Labor Day 2026 through tentative last day May 28 2027
    year_start = date(2026, 8, 17)  # district often starts mid/late August; CSV lacks first day
    year_end = date(2027, 5, 28)
    if day < year_start or day > year_end:
        return False, "outside the published 2026–2027 school-year window in this calendar"
    return True, "regular school day (not listed as a no-school date)"


def _parse_named_date(text: str) -> date | None:
    cleaned = (text or "").lower()
    # Month day year / month day
    months = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    m = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|"
        r"october|november|december)\s+(\d{1,2})(?:,?\s*(\d{4}))?\b",
        cleaned,
    )
    if m:
        month = months[m.group(1)]
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else chicago_today().year
        try:
            return date(year, month, day)
        except ValueError:
            return None
    m2 = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", cleaned)
    if m2:
        month, day = int(m2.group(1)), int(m2.group(2))
        year_raw = m2.group(3)
        year = chicago_today().year if not year_raw else int(year_raw)
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _find_break(keyword: str) -> dict[str, Any] | None:
    key = keyword.lower()
    for ev in list_events():
        name = (ev.get("name") or "").lower()
        if key in name:
            return ev
    return None


def _wants_winter_holiday_season(cleaned: str) -> bool:
    """Christmas / New Year / 'the holidays' → Winter Break season."""
    if re.search(r"\bchristmas\b", cleaned):
        return True
    if re.search(r"\bnew\s*year'?s?\b", cleaned):
        return True
    if re.search(r"\baround the holidays\b", cleaned):
        return True
    if re.search(r"\b(the\s+)?holidays\b", cleaned) and re.search(
        r"\b(time off|days? off|break|vacation|off|no school)\b", cleaned
    ):
        return True
    if re.search(r"\blong break\b", cleaned) and re.search(
        r"\b(christmas|new\s*year|holiday|winter|december|january)\b", cleaned
    ):
        return True
    return False


def _winter_break_answer() -> dict[str, Any]:
    ev = _find_break("winter")
    if not ev:
        return _result(
            "No winter / holiday-season break dates are listed in the "
            "imported district calendar."
        )
    return _result(
        f"{ev.get('name')} is {_format_range(ev)} "
        f"(student attendance: {ev.get('student_attendance') or 'No School'}). "
        "That covers the Christmas / New Year holiday period on the district calendar.",
        [ev],
    )


def _next_holiday_after(day: date) -> dict[str, Any] | None:
    upcoming = []
    for start, end, ev in _no_school_ranges():
        if end < day:
            continue
        et = (ev.get("event_type") or "").lower()
        name = (ev.get("name") or "").lower()
        if et in {"holiday", "break"} or "break" in name or "holiday" in name:
            upcoming.append((start, ev))
    upcoming.sort(key=lambda item: item[0])
    return upcoming[0][1] if upcoming else None


def _format_range(ev: dict[str, Any]) -> str:
    start = ev.get("start_date")
    end = ev.get("end_date") or start
    if start == end:
        return str(start)
    return f"{start} through {end}"


_MONTH_NAME_TO_NUM = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def _mentioned_months(text: str) -> set[int]:
    cleaned = (text or "").lower()
    found: set[int] = set()
    for name, num in _MONTH_NAME_TO_NUM.items():
        if re.search(rf"\b{name}\b", cleaned):
            found.add(num)
    return found


def _range_overlaps_months(start: date, end: date, months: set[int]) -> bool:
    day = start
    while day <= end:
        if day.month in months:
            return True
        day += timedelta(days=1)
        if (day - start).days > 120:
            # Safety for bad ranges.
            break
    return False


def _no_school_events_for_months(months: set[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for start, end, ev in _no_school_ranges():
        if _range_overlaps_months(start, end, months):
            out.append(ev)
    return out


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _group_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group events that describe the same thing (same dates + name).

    District 204 and Crone can both list e.g. Parent/Teacher Conferences on the same
    day. They are shown as one line, using the row that carries times/notes.
    """
    groups: dict[tuple[date, date, str], dict[str, Any]] = {}
    for ev in events:
        start = parse_iso_date(ev.get("start_date") or "")
        if not start:
            continue
        end = parse_iso_date(ev.get("end_date") or "") or start
        key = (start, end, _norm_name(ev.get("name") or ""))
        group = groups.setdefault(
            key, {"start": start, "end": end, "name": ev.get("name") or "", "events": []}
        )
        group["events"].append(ev)
    out: list[dict[str, Any]] = []
    for group in groups.values():
        evs = group["events"]
        primary = next((e for e in evs if (e.get("notes") or "").strip()), evs[0])
        evs.sort(key=lambda e: e is not primary)
        group["notes"] = (primary.get("notes") or "").strip()
        group["name"] = primary.get("name") or group["name"]
        group["no_school"] = any(
            "no school" in (e.get("student_attendance") or "").lower() for e in evs
        )
        out.append(group)
    out.sort(key=lambda g: (g["start"], g["name"]))
    return out


def _format_day(day: date) -> str:
    return f"{day.strftime('%A, %b')} {day.day}, {day.year}"


def _group_when(group: dict[str, Any]) -> str:
    if group["start"] == group["end"]:
        return _format_day(group["start"])
    return f"{_format_day(group['start'])} through {_format_day(group['end'])}"


def _group_sentence(group: dict[str, Any], today: date) -> str:
    past = group["end"] < today
    notes = f" ({group['notes']})" if group["notes"] else ""
    text = f"{group['name']}: {_group_when(group)}{notes}."
    if group["no_school"]:
        text += " Students had no school." if past else " Students have no school."
    if past:
        text += " That date has already passed."
    return text


def _group_line(group: dict[str, Any]) -> str:
    notes = f" ({group['notes']})" if group["notes"] else ""
    suffix = " — no school for students" if group["no_school"] else ""
    return f"• {group['name']}: {_group_when(group)}{notes}{suffix}"


_MAX_LISTED = 5


def _lookup_result(
    events: list[dict[str, Any]], cleaned: str, today: date
) -> dict[str, Any]:
    """Answer "when is <event>" from matched events (with each event's own source)."""
    groups = _group_events(events)
    months = _mentioned_months(cleaned)
    if months:
        in_month = [g for g in groups if g["start"].month in months]
        groups = in_month or groups
    upcoming = [g for g in groups if g["end"] >= today]
    past = [g for g in groups if g["end"] < today]
    wants_next = bool(re.search(r"\b(next|upcoming|soon|coming)\b", cleaned))
    wants_past = bool(re.search(r"\b(was|were|did|happened|ago)\b", cleaned))

    shown: list[dict[str, Any]]
    if wants_past and past:
        shown = [past[-1]]
        body = _group_sentence(shown[0], today)
    elif upcoming:
        if wants_next or len(upcoming) == 1:
            shown = [upcoming[0]]
            body = _group_sentence(shown[0], today)
        else:
            shown = upcoming[:_MAX_LISTED]
            lines = [_group_line(g) for g in shown]
            extra = len(upcoming) - len(shown)
            if extra > 0:
                lines.append(f"…and {extra} more later in the year.")
            body = "Upcoming dates:\n" + "\n".join(lines)
    elif past:
        shown = [past[-1]]
        body = _group_sentence(shown[0], today)
        if len(past) > 1:
            body = "There are no more upcoming dates listed. Most recent: " + body
    else:
        return _result("I could not find that event on the school calendars.")
    sources_from = [ev for g in shown for ev in g["events"]]
    return _result(body, sources_from)


def _events_named(norm: str) -> list[dict[str, Any]]:
    return [ev for ev in list_events() if _norm_name(ev.get("name") or "") == norm]


def answer_calendar_question(text: str, *, today: date | None = None) -> dict[str, Any]:
    """Return {answer, handled}. handled False means fall through to FAQ."""
    today = today or chicago_today()
    cleaned = (text or "").lower()

    # First / last day — from school-event rows when present, else fallback wording.
    if re.search(r"\bwhen does school start\b|\bfirst day of school\b", cleaned):
        first = _events_named("firstdayofschool")
        if first:
            return _lookup_result(first, cleaned, today)
        return _result(
            "The imported District 204 calendar lists no-school dates and breaks, "
            "but it does not include a confirmed first day of school. "
            "Please check the official district calendar PDF for the start date."
        )
    if re.search(r"\blast day of school\b", cleaned):
        last = _events_named("lastdayofschool")
        if last:
            return _lookup_result(last, cleaned, today)
        tentative = None
        for ev in list_events():
            if "teacher work day" in (ev.get("name") or "").lower() and "tentative" in (
                (ev.get("notes") or "") + (ev.get("name") or "")
            ).lower():
                tentative = ev
                break
        if tentative:
            return _result(
                "The district calendar notes a tentative last day of school around "
                "May 28, 2027 (see tentative Teacher Work Day notes). "
                "Treat this as tentative until confirmed on the official calendar.",
                [tentative],
            )
        return _result(
            "No confirmed last day of school is listed as a standalone event in the "
            "imported calendar. Please check the official district calendar PDF."
        )

    m_until = re.search(r"how many days until\s+(.+?)(?:\?|$)", cleaned)
    if m_until:
        target_name = m_until.group(1).strip()
        ev = None
        if "spring" in target_name:
            ev = _find_break("spring")
        elif "winter" in target_name:
            ev = _find_break("winter")
        elif "thanksgiving" in target_name:
            ev = _find_break("thanksgiving")
        elif target_name:
            groups = [
                g
                for g in _group_events(find_events_by_name(target_name))
                if g["end"] >= today
            ]
            if groups:
                ev = groups[0]["events"][0]
            else:
                first_word = re.sub(r"^(the|a|an)\s+", "", target_name).split(" ")[0]
                ev = _find_break(first_word) if first_word else None
        if not ev:
            return _result(
                "I could not find that break/holiday on the imported district calendar."
            )
        start = parse_iso_date(ev.get("start_date") or "")
        if not start:
            return _result("That event is listed but its start date could not be parsed.")
        delta = (start - today).days
        if delta < 0:
            msg = (
                f"{ev.get('name')} already started or ended relative to today "
                f"({today.isoformat()}). Listed dates: {_format_range(ev)}."
            )
        elif delta == 0:
            msg = f"{ev.get('name')} starts today ({today.isoformat()})."
        else:
            msg = (
                f"There are {delta} days until {ev.get('name')} begins on "
                f"{start.isoformat()} (today is {today.isoformat()})."
            )
        return _result(msg, [ev])

    for label, key in (
        ("thanksgiving", "thanksgiving"),
        ("winter break", "winter"),
        ("spring break", "spring"),
    ):
        if label in cleaned:
            ev = _find_break(key)
            if not ev:
                return _result(
                    f"No {label} dates are listed in the imported district calendar."
                )
            return _result(
                f"{ev.get('name')} is {_format_range(ev)} "
                f"(student attendance: {ev.get('student_attendance') or 'No School'}).",
                [ev],
            )

    # "winter" / "holiday break" without the word "break" next to winter, etc.
    if re.search(r"\bwinter\b", cleaned) and re.search(
        r"\b(break|holiday|off|vacation|time off|days off)\b", cleaned
    ):
        return _winter_break_answer()

    # Christmas / New Year / "time off around the holidays"
    if _wants_winter_holiday_season(cleaned):
        return _winter_break_answer()

    # Month / season time-off questions (e.g. December/January).
    months = _mentioned_months(cleaned)
    if months and re.search(
        r"\b(time off|days? off|no school|holiday|break|vacation|off from school)\b"
        r"|\bis there school\b",
        cleaned,
    ):
        events = _no_school_events_for_months(months)
        if events:
            lines = [
                f"• {ev.get('name')}: {_format_range(ev)} "
                f"({ev.get('student_attendance') or 'No School'})"
                for ev in events
            ]
            month_label = "/".join(
                datetime(2000, m, 1).strftime("%B") for m in sorted(months)
            )
            return _result(
                f"District calendar no-school dates overlapping {month_label}:\n"
                + "\n".join(lines),
                events,
            )
        return _result(
            "I could not find matching no-school dates for that period "
            "in the imported district calendar."
        )

    if re.search(
        r"\bnext\s+(school\s+)?(holiday|break)\b|\bupcoming\s+(school\s+)?(holiday|break)\b",
        cleaned,
    ):
        ev = _next_holiday_after(today)
        if not ev:
            return _result(
                "No upcoming holiday/break is listed after today in the imported calendar."
            )
        return _result(
            f"The next listed holiday/break is {ev.get('name')} ({_format_range(ev)}).",
            [ev],
        )

    target = None
    if re.search(r"\btoday\b", cleaned) and re.search(r"\bschool\b", cleaned):
        target = today
    elif re.search(r"\btomorrow\b", cleaned) and re.search(r"\bschool\b", cleaned):
        target = today + timedelta(days=1)
    else:
        named = _parse_named_date(cleaned)
        if named and re.search(r"\bschool\b|\bno school\b", cleaned):
            target = named

    if target is not None:
        ok, reason = is_school_day(target)
        if ok:
            body = f"Yes — {target.isoformat()} looks like a school day ({reason})."
        else:
            body = f"No — there is not school on {target.isoformat()} ({reason})."
        return _result(body)

    # "When is <event>?" — match an event by name (Fall Fest, PTSA meeting, …).
    matched = find_events_by_name(cleaned)
    if matched:
        return _lookup_result(matched, cleaned, today)

    return {"handled": False, "answer": None}
