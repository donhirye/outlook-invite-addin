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
    r"\bparent/?teacher conference\b",
)


def looks_like_calendar_question(text: str) -> bool:
    cleaned = (text or "").lower()
    return any(re.search(pat, cleaned) for pat in CALENDAR_PATTERNS)


def _source_footer() -> str:
    meta = get_calendar_meta()
    name = meta.get("source_name") or DEFAULT_SOURCE_NAME
    url = meta.get("source_url") or DEFAULT_SOURCE_URL
    return f"Source: {name}\n{url}"


def format_calendar_answer(body: str) -> str:
    return f"*School calendar*\n{(body or '').strip()}\n\n_{_source_footer()}_"


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


def answer_calendar_question(text: str, *, today: date | None = None) -> dict[str, Any]:
    """Return {answer, handled}. handled False means fall through to FAQ."""
    today = today or chicago_today()
    cleaned = (text or "").lower()
    meta = get_calendar_meta()

    # First / last day — calendar CSV may not include them explicitly.
    if re.search(r"\bwhen does school start\b|\bfirst day of school\b", cleaned):
        return {
            "handled": True,
            "answer": format_calendar_answer(
                "The imported District 204 calendar lists no-school dates and breaks, "
                "but it does not include a confirmed first day of school. "
                "Please check the official district calendar PDF for the start date."
            ),
            "source_name": meta.get("source_name"),
            "source_url": meta.get("source_url"),
        }
    if re.search(r"\blast day of school\b", cleaned):
        tentative = None
        for ev in list_events():
            if "teacher work day" in (ev.get("name") or "").lower() and "tentative" in (
                (ev.get("notes") or "") + (ev.get("name") or "")
            ).lower():
                tentative = ev
                break
        if tentative:
            return {
                "handled": True,
                "answer": format_calendar_answer(
                    "The district calendar notes a tentative last day of school around "
                    "May 28, 2027 (see tentative Teacher Work Day notes). "
                    "Treat this as tentative until confirmed on the official calendar."
                ),
                "source_name": meta.get("source_name"),
                "source_url": meta.get("source_url"),
            }
        return {
            "handled": True,
            "answer": format_calendar_answer(
                "No confirmed last day of school is listed as a standalone event in the "
                "imported calendar. Please check the official district calendar PDF."
            ),
            "source_name": meta.get("source_name"),
            "source_url": meta.get("source_url"),
        }

    m_until = re.search(r"how many days until\s+(.+?)(?:\?|$)", cleaned)
    if m_until:
        target_name = m_until.group(1).strip()
        ev = _find_break(target_name.split()[0]) if target_name else None
        if "spring" in target_name:
            ev = _find_break("spring")
        elif "winter" in target_name:
            ev = _find_break("winter")
        elif "thanksgiving" in target_name:
            ev = _find_break("thanksgiving")
        if not ev:
            return {
                "handled": True,
                "answer": format_calendar_answer(
                    "I could not find that break/holiday on the imported district calendar."
                ),
                "source_name": meta.get("source_name"),
                "source_url": meta.get("source_url"),
            }
        start = parse_iso_date(ev.get("start_date") or "")
        if not start:
            return {
                "handled": True,
                "answer": format_calendar_answer(
                    "That event is listed but its start date could not be parsed."
                ),
                "source_name": meta.get("source_name"),
                "source_url": meta.get("source_url"),
            }
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
        return {
            "handled": True,
            "answer": format_calendar_answer(msg),
            "source_name": meta.get("source_name"),
            "source_url": meta.get("source_url"),
        }

    for label, key in (
        ("thanksgiving", "thanksgiving"),
        ("winter break", "winter"),
        ("spring break", "spring"),
    ):
        if label in cleaned or (key == "thanksgiving" and "thanksgiving" in cleaned):
            ev = _find_break(key if key != "thanksgiving" else "thanksgiving")
            if not ev:
                return {
                    "handled": True,
                    "answer": format_calendar_answer(
                        f"No {label} dates are listed in the imported district calendar."
                    ),
                    "source_name": meta.get("source_name"),
                    "source_url": meta.get("source_url"),
                }
            return {
                "handled": True,
                "answer": format_calendar_answer(
                    f"{ev.get('name')} is {_format_range(ev)} "
                    f"(student attendance: {ev.get('student_attendance') or 'No School'})."
                ),
                "source_name": meta.get("source_name"),
                "source_url": meta.get("source_url"),
            }

    if re.search(r"\bnext\s+(school\s+)?(holiday|break)\b|\bupcoming\s+(school\s+)?(holiday|break)\b", cleaned):
        ev = _next_holiday_after(today)
        if not ev:
            return {
                "handled": True,
                "answer": format_calendar_answer(
                    "No upcoming holiday/break is listed after today in the imported calendar."
                ),
                "source_name": meta.get("source_name"),
                "source_url": meta.get("source_url"),
            }
        return {
            "handled": True,
            "answer": format_calendar_answer(
                f"The next listed holiday/break is {ev.get('name')} "
                f"({_format_range(ev)})."
            ),
            "source_name": meta.get("source_name"),
            "source_url": meta.get("source_url"),
        }

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
        return {
            "handled": True,
            "answer": format_calendar_answer(body),
            "source_name": meta.get("source_name"),
            "source_url": meta.get("source_url"),
        }

    return {"handled": False, "answer": None}
