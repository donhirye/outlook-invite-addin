"""Date-list / 'what's going on' overview: full calendar + dated FAQ scan."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from app.calendar_service import is_faq_action_question
from app.calendar_store import list_events, parse_iso_date
from app.faq_records import chicago_today, list_records

_MONTHS = {
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

_OVERVIEW_CUES = re.compile(
    r"\b("
    r"what(?:'s|s| is)?\s+going\s+on|"
    r"what(?:'s|s| is)?\s+(?:all\s+)?(?:on|happening)|"
    r"anything\s+happening|"
    r"(?:show|list|tell|give|send)\s+me\s+(?:all\s+)?(?:the\s+)?events?|"
    r"all\s+(?:the\s+)?events?|"
    r"events?\s+(?:in|between|from|for|through)|"
    r"what\s+events?|"
    r"upcoming\s+events?|"
    r"show\s+me\s+(?:the\s+)?(?:school\s+)?calendars?|"
    r"what(?:'s|s| is)?\s+on\s+the\s+(?:school\s+)?calendars?"
    r")\b",
    re.I,
)

_DATE_IN_TEXT_RE = re.compile(
    r"\b("
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?"
    r"(?:\s*[\u2013\-]\s*\d{1,2}(?:st|nd|rd|th)?)?"
    r"(?:,?\s*\d{4})?"
    r"|"
    r"\d{1,2}/\d{1,2}/\d{2,4}"
    r"|"
    r"\d{4}-\d{2}-\d{2}"
    r")\b",
    re.I,
)

_DEADLINE_RE = re.compile(
    r"\b(order\s+by|due\s+by|due\s+on|deadline|through|open\s+through|by\s+\w+\s+\d{1,2})\b",
    re.I,
)
_PICKUP_RE = re.compile(r"\b(pick\s*up|pickup|available\s+for\s+pickup)\b", re.I)

_SIBLING_STOP = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at", "is", "are",
    "be", "by", "with", "from", "about", "what", "when", "where", "how", "do", "does",
    "can", "will", "please", "crone", "middle", "school", "ptsa", "parent", "parents",
    "event", "events", "date", "dates", "faq", "newsletter", "weekly",
}


def is_overview_question(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned or is_faq_action_question(cleaned):
        return False
    if not _OVERVIEW_CUES.search(cleaned):
        # "in may 2027" / "december events" style without explicit cue words
        if re.search(
            r"\b(events?|happening|going\s+on)\b.*\b("
            + "|".join(_MONTHS)
            + r")\b",
            cleaned,
            re.I,
        ):
            return True
        if re.search(
            r"\b(" + "|".join(_MONTHS) + r")\b.*\b(events?|happening|going\s+on)\b",
            cleaned,
            re.I,
        ):
            return True
        return False
    return True


def _parse_mdy(raw: str) -> date | None:
    s = re.sub(r"(st|nd|rd|th)", "", (raw or "").strip(), flags=re.I)
    s = re.sub(r",", "", s)
    # Ranges like "May 29-30 2027" → use the first day
    s = re.sub(r"(\d{1,2})\s*[\u2013\-]\s*\d{1,2}", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Yearless month-day: parse with a leap-safe sentinel year, then tag for caller.
    for fmt in ("%B %d", "%b %d"):
        try:
            dt = datetime.strptime(f"{s} 2000", f"{fmt} %Y")
            return date(1900, dt.month, dt.day)
        except ValueError:
            continue
    return None


def parse_date_window(text: str, *, today: date | None = None) -> tuple[date, date]:
    """Return inclusive [start, end] for an overview ask."""
    today = today or chicago_today()
    cleaned = (text or "").lower()

    # between now and end of YYYY
    m = re.search(
        r"between\s+now\s+and\s+(?:the\s+)?end\s+of\s+(\d{4})",
        cleaned,
    )
    if m:
        return today, date(int(m.group(1)), 12, 31)

    # from now through / until end of YYYY
    m = re.search(r"(?:through|until|till)\s+(?:the\s+)?end\s+of\s+(\d{4})", cleaned)
    if m:
        return today, date(int(m.group(1)), 12, 31)

    # Month + optional year
    m = re.search(
        r"\b(" + "|".join(_MONTHS.keys()) + r")\b(?:\s+(\d{4}))?",
        cleaned,
    )
    if m:
        month = _MONTHS[m.group(1)]
        year = int(m.group(2)) if m.group(2) else None
        if year is None:
            # upcoming occurrence of that month
            year = today.year
            if date(year, month, 1) < date(today.year, today.month, 1):
                year += 1
        start = date(year, month, 1)
        if month == 12:
            end = date(year, 12, 31)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
        return start, end

    # Default for bare "show me the calendar" / "upcoming events": next 90 days
    return today, today + timedelta(days=90)


def classify_date_kind(context: str) -> str:
    ctx = context or ""
    if _PICKUP_RE.search(ctx):
        return "pickup"
    if _DEADLINE_RE.search(ctx):
        return "deadline"
    return "event"


def extract_dates_from_text(text: str, *, default_year: int | None = None) -> list[date]:
    """Parse calendar-ish dates mentioned in FAQ Q/A text."""
    today = chicago_today()
    year = default_year or today.year
    out: list[date] = []
    for raw in _DATE_IN_TEXT_RE.findall(text or ""):
        d = _parse_mdy(raw)
        if not d:
            continue
        if d.year == 1900:
            # Prefer school-year-ish: if month < current and no year, may be next year
            y = year
            candidate = date(y, d.month, d.day)
            # Also try year-1 / year+1 when string had no year — keep both if needed by caller
            out.append(candidate)
            if candidate.month < today.month and not re.search(r"\d{4}", raw):
                out.append(date(y + 1, d.month, d.day))
        else:
            out.append(d)
    # de-dupe preserve order
    seen: set[date] = set()
    uniq: list[date] = []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def _tokens(text: str) -> set[str]:
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {t for t in toks if len(t) > 2 and t not in _SIBLING_STOP}


def find_sibling_records(
    primary: dict[str, Any],
    *,
    records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Other Active FAQ rows about the same item (strong token overlap)."""
    pool = records if records is not None else list_records(include_inactive=False)
    pid = primary.get("faq_id")
    base = _tokens(
        f"{primary.get('question') or ''} {primary.get('answer') or ''} "
        f"{primary.get('category') or ''}"
    )
    # Prefer distinctive tokens (numbers, proper-ish lengths)
    strong = {t for t in base if t.isdigit() or len(t) >= 5}
    if len(strong) < 2:
        strong = base
    if len(strong) < 2:
        return []
    siblings: list[dict[str, Any]] = []
    for rec in pool:
        if rec.get("faq_id") == pid:
            continue
        other = _tokens(
            f"{rec.get('question') or ''} {rec.get('answer') or ''} "
            f"{rec.get('category') or ''}"
        )
        if not other:
            continue
        overlap = strong & other
        # Need at least 2 strong shared tokens, or 1 long shared entity + category match
        if len(overlap) >= 2:
            siblings.append(rec)
            continue
        if (
            len(overlap) >= 1
            and (primary.get("category") or "") == (rec.get("category") or "")
            and any(len(t) >= 6 for t in overlap)
        ):
            siblings.append(rec)
    return siblings


def _faq_dates_for_record(rec: dict[str, Any]) -> list[tuple[date, str]]:
    """Dates that 'belong' to this FAQ row, with kinds."""
    text = f"{rec.get('question') or ''}\n{rec.get('answer') or ''}"
    dated: list[tuple[date, str]] = []
    ed = (rec.get("event_date") or "").strip()
    if ed:
        from app.faq_records import _parse_event_date

        d = _parse_event_date(ed)
        if d:
            dated.append((d, classify_date_kind(text)))
    for d in extract_dates_from_text(text):
        # local context window around the date string for kind
        kind = classify_date_kind(text)
        # refine: if pickup phrase near this month mention
        month_name = d.strftime("%B").lower()
        if month_name in text.lower():
            # find snippet containing month
            idx = text.lower().find(month_name)
            snippet = text[max(0, idx - 40) : idx + 60]
            kind = classify_date_kind(snippet)
        dated.append((d, kind))
    # de-dupe by date keeping first kind
    seen: set[date] = set()
    out: list[tuple[date, str]] = []
    for d, k in dated:
        if d in seen:
            continue
        seen.add(d)
        out.append((d, k))
    return out


def faq_rows_in_window(
    start: date,
    end: date,
    *,
    records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """FAQ records with at least one date inside [start, end]."""
    pool = records if records is not None else list_records(include_inactive=False)
    hits: list[dict[str, Any]] = []
    for rec in pool:
        in_window: list[tuple[date, str]] = []
        all_dates = _faq_dates_for_record(rec)
        for d, kind in all_dates:
            if start <= d <= end:
                in_window.append((d, kind))
        if not in_window:
            continue
        hits.append(
            {
                "record": rec,
                "in_window_dates": in_window,
                "all_dates": all_dates,
            }
        )
    hits.sort(
        key=lambda h: (
            min(d for d, _ in h["in_window_dates"]),
            h["record"].get("faq_id") or "",
        )
    )
    return hits


def calendar_events_in_window(start: date, end: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in list_events():
        s = parse_iso_date(ev.get("start_date") or "")
        e = parse_iso_date(ev.get("end_date") or "") or s
        if not s:
            continue
        # overlap with window
        if e < start or s > end:
            continue
        out.append(ev)
    return out


def _fmt_cal_line(ev: dict[str, Any]) -> str:
    name = ev.get("name") or "Event"
    start = ev.get("start_date") or ""
    end = ev.get("end_date") or start
    cal = ev.get("calendar_name") or ev.get("source_name") or "Calendar"
    if end and end != start:
        when = f"{start} to {end}"
    else:
        when = start
    return f"• {when} — {name} ({cal})"


def _fmt_faq_line(hit: dict[str, Any], *, start: date, end: date) -> str:
    rec = hit["record"]
    q = (rec.get("question") or "").strip()
    a = (rec.get("answer") or "").strip()
    parts: list[str] = []
    for d, kind in hit["in_window_dates"]:
        label = {
            "deadline": "deadline",
            "pickup": "pickup",
            "event": "event",
            "other": "date",
        }.get(kind, "date")
        parts.append(f"{d.isoformat()} ({label})")
    head = ", ".join(parts)
    summary = a if len(a) <= 220 else a[:217].rstrip() + "…"
    line = f"• {head} — {q}: {summary}"
    # Related follow-ups: sibling dates outside window
    siblings = find_sibling_records(rec)
    follow: list[str] = []
    for sib in siblings:
        for d, kind in _faq_dates_for_record(sib):
            if start <= d <= end:
                continue
            label = {
                "deadline": "deadline",
                "pickup": "pickup",
                "event": "event",
            }.get(kind, "date")
            follow.append(
                f"Related follow-up: {d.isoformat()} ({label}) — "
                f"{(sib.get('answer') or '')[:160]}"
            )
    if follow:
        # de-dupe
        seen: set[str] = set()
        uniq = []
        for f in follow:
            if f in seen:
                continue
            seen.add(f)
            uniq.append(f)
        line += "\n  " + "\n  ".join(uniq[:3])
    return line


def answer_overview(
    text: str,
    *,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Full dual-source overview. None if not an overview question."""
    if not is_overview_question(text):
        return None
    today = today or chicago_today()
    start, end = parse_date_window(text, today=today)
    cal = calendar_events_in_window(start, end)
    faq_hits = faq_rows_in_window(start, end)

    chunks: list[str] = []
    sections: list[str] = [
        f"*What's going on ({start.isoformat()} → {end.isoformat()})*"
    ]

    if cal:
        sections.append("*School / PTSA calendar*")
        for ev in cal[:80]:
            line = _fmt_cal_line(ev)
            sections.append(line)
            chunks.append(
                f"[calendar] {ev.get('start_date')} {ev.get('name')} "
                f"({ev.get('calendar_name') or ev.get('source_name')})"
            )
    if faq_hits:
        sections.append("*PTSA announcements & deadlines (from FAQ)*")
        for hit in faq_hits[:60]:
            sections.append(_fmt_faq_line(hit, start=start, end=end))
            rec = hit["record"]
            chunks.append(
                f"[faq {rec.get('faq_id')}] "
                + "; ".join(f"{d} ({k})" for d, k in hit["in_window_dates"])
                + f"\nQ: {rec.get('question')}\nA: {rec.get('answer')}"
            )
            # Include sibling follow-up evidence in chunks for coverage checks
            for sib in find_sibling_records(rec):
                sib_dates = _faq_dates_for_record(sib)
                outside = [(d, k) for d, k in sib_dates if not (start <= d <= end)]
                if outside:
                    chunks.append(
                        f"[faq-sibling {sib.get('faq_id')}] "
                        + "; ".join(f"{d} ({k})" for d, k in outside)
                        + f"\nQ: {sib.get('question')}\nA: {sib.get('answer')}"
                    )

    if not cal and not faq_hits:
        sections.append(
            "I couldn't find calendar events or dated FAQ items in that window. "
            "Please check the school calendar or ask PTSA Administrators."
        )

    sources = ["school_calendar", "faq_records"]
    source_names: list[str] = []
    for ev in cal[:5]:
        n = (ev.get("source_name") or ev.get("calendar_name") or "").strip()
        if n and n not in source_names:
            source_names.append(n)
    for hit in faq_hits[:5]:
        n = (hit["record"].get("source") or "").strip()
        if n and n not in source_names:
            source_names.append(n)

    return {
        "messages": ["\n".join(sections)],
        "route": "overview",
        "intent": "overview",
        "retrieval_mode": "overview",
        "answer_outcome": "answered" if (cal or faq_hits) else "unanswered",
        "sources": sources,
        "source_name": "; ".join(source_names) if source_names else None,
        "source_url": None,
        "retrieved_chunks": chunks,
        "faq_id": None,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
    }


def format_sibling_topic_answer(
    primary: dict[str, Any],
    siblings: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Deterministic multi-row FAQ body + evidence chunk lines for a topic ask."""
    rows = [primary] + [s for s in siblings if s.get("faq_id") != primary.get("faq_id")]
    lines: list[str] = []
    chunks: list[str] = []
    for rec in rows:
        dates = _faq_dates_for_record(rec)
        date_bits = [f"{d.isoformat()} ({kind})" for d, kind in dates]
        date_prefix = (", ".join(date_bits) + " — ") if date_bits else ""
        ans = (rec.get("answer") or "").strip()
        lines.append(f"• {date_prefix}{ans}")
        chunks.append(
            f"[faq {rec.get('faq_id')}] "
            + ("; ".join(date_bits) if date_bits else "no-date")
            + f"\nQ: {rec.get('question')}\nA: {ans}"
        )
    return "\n".join(lines), chunks
