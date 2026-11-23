"""Date-list / 'what's going on' overview: calendar + per-date FAQ bullets."""

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
    r"\b(order\s+by|due\s+by|due\s+on|deadline|through|open\s+through|"
    r"last\s+day\s+to|close[sd]?|sales?\s+are\s+open)\b",
    re.I,
)
_PICKUP_RE = re.compile(r"\b(pick\s*up|pickup|available\s+for\s+pickup)\b", re.I)

_SIBLING_STOP = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at", "is", "are",
    "be", "by", "with", "from", "about", "what", "when", "where", "how", "do", "does",
    "can", "will", "please", "crone", "middle", "school", "ptsa", "parent", "parents",
    "event", "events", "date", "dates", "faq", "newsletter", "weekly", "upcoming",
    "scheduled", "against", "grade", "grades", "meeting", "informational",
}


def is_overview_question(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned or is_faq_action_question(cleaned):
        return False
    if not _OVERVIEW_CUES.search(cleaned):
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
    s = re.sub(r"(\d{1,2})\s*[\u2013\-]\s*\d{1,2}", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
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

    m = re.search(
        r"between\s+now\s+and\s+(?:the\s+)?end\s+of\s+(\d{4})",
        cleaned,
    )
    if m:
        return today, date(int(m.group(1)), 12, 31)

    m = re.search(r"(?:through|until|till)\s+(?:the\s+)?end\s+of\s+(\d{4})", cleaned)
    if m:
        return today, date(int(m.group(1)), 12, 31)

    m = re.search(
        r"\b(" + "|".join(_MONTHS.keys()) + r")\b(?:\s+(\d{4}))?",
        cleaned,
    )
    if m:
        month = _MONTHS[m.group(1)]
        year = int(m.group(2)) if m.group(2) else None
        if year is None:
            year = today.year
            if date(year, month, 1) < date(today.year, today.month, 1):
                year += 1
        start = date(year, month, 1)
        if month == 12:
            end = date(year, 12, 31)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
        return start, end

    return today, today + timedelta(days=90)


def classify_date_kind(context: str) -> str:
    ctx = context or ""
    if _PICKUP_RE.search(ctx):
        return "pickup"
    if _DEADLINE_RE.search(ctx):
        return "deadline"
    return "event"


def _stem(tok: str) -> str:
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def _tokens(text: str) -> set[str]:
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {_stem(t) for t in toks if len(t) > 2 and t not in _SIBLING_STOP}


def _entity_tokens(rec: dict[str, Any]) -> set[str]:
    """Distinctive tokens from question (+ light answer boost)."""
    q = _tokens(rec.get("question") or "")
    a = _tokens(rec.get("answer") or "")
    # Prefer question nouns; keep long/digit tokens from answer too
    strong_a = {t for t in a if t.isdigit() or len(t) >= 6}
    return q | strong_a


def find_sibling_records(
    primary: dict[str, Any],
    *,
    records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Strict same-item siblings for topic asks (not used for overview related junk)."""
    pool = records if records is not None else list_records(include_inactive=False)
    pid = primary.get("faq_id")
    base = _entity_tokens(primary)
    strong = {t for t in base if t.isdigit() or len(t) >= 5}
    if len(strong) < 3:
        return []
    siblings: list[dict[str, Any]] = []
    for rec in pool:
        if rec.get("faq_id") == pid:
            continue
        other = _entity_tokens(rec)
        overlap = strong & other
        if len(overlap) < 3:
            continue
        # Require a digit (class year / id-ish) or a long shared product token
        if not any(t.isdigit() or len(t) >= 6 for t in overlap):
            continue
        jaccard = len(overlap) / max(1, len(strong | {t for t in other if t in strong or len(t) >= 5}))
        if jaccard < 0.35 and len(overlap) < 4:
            continue
        siblings.append(rec)
    return siblings


def _resolve_yearless(
    d: date,
    raw: str,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
    default_year: int | None = None,
) -> date | None:
    if d.year != 1900:
        return d
    years: list[int] = []
    if window_start and window_end:
        years.extend(range(window_start.year, window_end.year + 1))
    y0 = default_year or chicago_today().year
    years.extend([y0, y0 + 1, y0 - 1])
    seen: set[int] = set()
    for y in years:
        if y in seen:
            continue
        seen.add(y)
        try:
            cand = date(y, d.month, d.day)
        except ValueError:
            continue
        if window_start and window_end:
            if window_start <= cand <= window_end:
                return cand
        else:
            return cand
    # Fallback: default year even if outside window (caller filters)
    try:
        return date(y0, d.month, d.day)
    except ValueError:
        return None


def iter_date_mentions(
    text: str,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
    default_year: int | None = None,
) -> list[dict[str, Any]]:
    """Each calendar date mention with span + local clause."""
    raw_text = text or ""
    mentions: list[dict[str, Any]] = []
    for m in _DATE_IN_TEXT_RE.finditer(raw_text):
        raw = m.group(1)
        parsed = _parse_mdy(raw)
        if not parsed:
            continue
        d = _resolve_yearless(
            parsed,
            raw,
            window_start=window_start,
            window_end=window_end,
            default_year=default_year,
        )
        if not d:
            continue
        # Clause: nearest segment split by . ; or newline around the match
        left = max(
            raw_text.rfind(".", 0, m.start()),
            raw_text.rfind(";", 0, m.start()),
            raw_text.rfind("\n", 0, m.start()),
        )
        right_candidates = [
            raw_text.find(".", m.end()),
            raw_text.find(";", m.end()),
            raw_text.find("\n", m.end()),
        ]
        right_idxs = [i for i in right_candidates if i >= 0]
        right = min(right_idxs) if right_idxs else len(raw_text)
        clause = raw_text[left + 1 : right].strip(" \t-:;")
        if not clause:
            clause = raw_text[max(0, m.start() - 80) : m.end() + 80].strip()
        kind = classify_date_kind(clause)
        mentions.append(
            {
                "date": d,
                "kind": kind,
                "raw": raw,
                "start": m.start(),
                "end": m.end(),
                "clause": clause,
            }
        )
    return mentions


def extract_dated_snippets(
    text: str,
    *,
    window_start: date,
    window_end: date,
    default_year: int | None = None,
) -> list[dict[str, Any]]:
    """One short blurb per date that falls inside the window."""
    mentions = iter_date_mentions(
        text,
        window_start=window_start,
        window_end=window_end,
        default_year=default_year,
    )
    by_date: dict[date, dict[str, Any]] = {}
    for ment in mentions:
        d = ment["date"]
        if not (window_start <= d <= window_end):
            continue
        prev = by_date.get(d)
        # Prefer longer/more specific clause; keep first kind unless deadline/pickup
        if prev is None or ment["kind"] in {"deadline", "pickup"} or len(
            ment["clause"]
        ) > len(prev["clause"]):
            by_date[d] = ment
    return [by_date[d] for d in sorted(by_date)]


def _faq_event_date(rec: dict[str, Any]) -> date | None:
    ed = (rec.get("event_date") or "").strip()
    if not ed:
        return None
    from app.faq_records import _parse_event_date

    return _parse_event_date(ed)


def faq_date_bullets_in_window(
    start: date,
    end: date,
    *,
    records: list[dict[str, Any]] | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Strict per-date FAQ bullets inside [start, end] (+ explicit linked notes)."""
    today = today or chicago_today()
    pool = records if records is not None else list_records(include_inactive=False)
    bullets: list[dict[str, Any]] = []

    for rec in pool:
        text = f"{rec.get('question') or ''}. {rec.get('answer') or ''}"
        snippets = extract_dated_snippets(
            text,
            window_start=start,
            window_end=end,
            default_year=start.year,
        )
        # Event_Date column alone (if in window and not already covered)
        ed = _faq_event_date(rec)
        if ed and start <= ed <= end and ed not in {s["date"] for s in snippets}:
            snippets.append(
                {
                    "date": ed,
                    "kind": classify_date_kind(text),
                    "clause": (rec.get("answer") or rec.get("question") or "").strip(),
                    "raw": ed.isoformat(),
                }
            )
            snippets.sort(key=lambda s: s["date"])

        for snip in snippets:
            blurb = _short_blurb(snip["clause"], snip["date"])
            bullets.append(
                {
                    "date": snip["date"],
                    "kind": snip["kind"],
                    "blurb": blurb,
                    "record": rec,
                    "linked_notes": [],
                }
            )

    # Explicit same-item continuations (e.g. shirt Dec 15 → Jan 13 pickup).
    # Only for deadline/order bullets; only high-precision entity overlap.
    for bullet in bullets:
        if bullet["kind"] not in {"deadline", "event"}:
            continue
        rec = bullet["record"]
        if not _DEADLINE_RE.search(
            f"{rec.get('question') or ''} {rec.get('answer') or ''}"
        ) and bullet["kind"] != "deadline":
            continue
        for other in pool:
            if other.get("faq_id") == rec.get("faq_id"):
                continue
            if not _explicitly_same_item(rec, other):
                continue
            other_text = f"{other.get('question') or ''}. {other.get('answer') or ''}"
            for ment in iter_date_mentions(other_text, default_year=end.year):
                d = ment["date"]
                if start <= d <= end:
                    continue
                if d < today:
                    continue
                # Prefer pickup / later follow-through
                if ment["kind"] not in {"pickup", "event", "deadline"}:
                    continue
                note = (
                    f"{d.isoformat()} ({ment['kind']}) — "
                    f"{_short_blurb(ment['clause'], d)}"
                )
                if note not in bullet["linked_notes"]:
                    bullet["linked_notes"].append(note)

        # Same-answer out-of-window dates (Jan mentioned in same FAQ as Dec deadline)
        same_text = f"{rec.get('question') or ''}. {rec.get('answer') or ''}"
        for ment in iter_date_mentions(same_text, default_year=end.year):
            d = ment["date"]
            if start <= d <= end or d < today:
                continue
            note = (
                f"{d.isoformat()} ({ment['kind']}) — "
                f"{_short_blurb(ment['clause'], d)}"
            )
            if note not in bullet["linked_notes"]:
                bullet["linked_notes"].append(note)

    bullets.sort(key=lambda b: (b["date"], b["record"].get("faq_id") or ""))
    return bullets


def _explicitly_same_item(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """High-precision same-item link (no generic similarity)."""
    ta = _entity_tokens(a)
    tb = _entity_tokens(b)
    strong_a = {t for t in ta if t.isdigit() or len(t) >= 5}
    strong_b = {t for t in tb if t.isdigit() or len(t) >= 5}
    overlap = strong_a & strong_b
    if len(overlap) < 3:
        return False
    if not any(t.isdigit() for t in overlap):
        # Without a year/id digit, require 4+ long shared tokens
        if len([t for t in overlap if len(t) >= 6]) < 2:
            return False
    return True


def _short_blurb(clause: str, d: date) -> str:
    text = re.sub(r"\s+", " ", (clause or "").strip())
    # Drop leading "Q: ..." if present
    text = re.sub(r"^.*?\?\s*", "", text, count=1) if "?" in text[:120] else text
    if len(text) > 160:
        text = text[:157].rstrip() + "…"
    return text or d.isoformat()


def calendar_events_in_window(start: date, end: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in list_events():
        s = parse_iso_date(ev.get("start_date") or "")
        e = parse_iso_date(ev.get("end_date") or "") or s
        if not s:
            continue
        if e < start or s > end:
            continue
        out.append(ev)
    return out


def _fmt_cal_line(ev: dict[str, Any]) -> str:
    name = ev.get("name") or "Event"
    start = ev.get("start_date") or ""
    end = ev.get("end_date") or start
    cal = ev.get("calendar_name") or ev.get("source_name") or "Calendar"
    when = f"{start} to {end}" if end and end != start else start
    return f"• {when} — {name} ({cal})"


def _fmt_faq_bullet(b: dict[str, Any]) -> str:
    kind = b.get("kind") or "event"
    line = f"• {b['date'].isoformat()} ({kind}) — {b['blurb']}"
    for note in (b.get("linked_notes") or [])[:1]:
        line += f"\n  Related follow-up: {note}"
    return line


def answer_overview(
    text: str,
    *,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Dual-source overview: calendar rows + per-date FAQ bullets only."""
    if not is_overview_question(text):
        return None
    today = today or chicago_today()
    start, end = parse_date_window(text, today=today)
    cal = calendar_events_in_window(start, end)
    faq_bullets = faq_date_bullets_in_window(start, end, today=today)

    chunks: list[str] = []
    sections: list[str] = [
        f"*What's going on ({start.isoformat()} → {end.isoformat()})*"
    ]

    if cal:
        sections.append("*School / PTSA calendar*")
        for ev in cal[:80]:
            sections.append(_fmt_cal_line(ev))
            chunks.append(
                f"[calendar] {ev.get('start_date')} {ev.get('name')} "
                f"({ev.get('calendar_name') or ev.get('source_name')})"
            )

    if faq_bullets:
        sections.append("*PTSA announcements & deadlines (from FAQ)*")
        for b in faq_bullets[:80]:
            sections.append(_fmt_faq_bullet(b))
            rec = b["record"]
            chunks.append(
                f"[faq {rec.get('faq_id')}] {b['date']} ({b['kind']})\n{b['blurb']}"
            )
            for note in b.get("linked_notes") or []:
                chunks.append(
                    f"[faq-linked {rec.get('faq_id')}] {note}"
                )

    if not cal and not faq_bullets:
        sections.append(
            "I couldn't find calendar events or dated FAQ items in that window. "
            "Please check the school calendar or ask PTSA Administrators."
        )

    source_names: list[str] = []
    for ev in cal[:5]:
        n = (ev.get("source_name") or ev.get("calendar_name") or "").strip()
        if n and n not in source_names:
            source_names.append(n)
    for b in faq_bullets[:8]:
        n = (b["record"].get("source") or "").strip()
        if n and n not in source_names:
            source_names.append(n)

    return {
        "messages": ["\n".join(sections)],
        "route": "overview",
        "intent": "overview",
        "retrieval_mode": "overview",
        "answer_outcome": "answered" if (cal or faq_bullets) else "unanswered",
        "sources": ["school_calendar", "faq_records"],
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
    """Deterministic multi-row FAQ body + evidence for a topic ask."""
    rows = [primary] + [s for s in siblings if s.get("faq_id") != primary.get("faq_id")]
    lines: list[str] = []
    chunks: list[str] = []
    for rec in rows:
        text = f"{rec.get('question') or ''}. {rec.get('answer') or ''}"
        mentions = iter_date_mentions(text)
        date_bits = []
        seen: set[date] = set()
        for ment in mentions:
            if ment["date"] in seen:
                continue
            seen.add(ment["date"])
            date_bits.append(f"{ment['date'].isoformat()} ({ment['kind']})")
        date_prefix = (", ".join(date_bits) + " — ") if date_bits else ""
        ans = (rec.get("answer") or "").strip()
        lines.append(f"• {date_prefix}{ans}")
        chunks.append(
            f"[faq {rec.get('faq_id')}] "
            + ("; ".join(date_bits) if date_bits else "no-date")
            + f"\nQ: {rec.get('question')}\nA: {ans}"
        )
    return "\n".join(lines), chunks


# Back-compat helpers used by older tests / callers
def extract_dates_from_text(text: str, *, default_year: int | None = None) -> list[date]:
    return [m["date"] for m in iter_date_mentions(text, default_year=default_year)]


def faq_rows_in_window(
    start: date,
    end: date,
    *,
    records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Legacy shape: records that contribute at least one in-window date bullet."""
    bullets = faq_date_bullets_in_window(start, end, records=records)
    by_id: dict[str, dict[str, Any]] = {}
    for b in bullets:
        rec = b["record"]
        fid = rec.get("faq_id") or id(rec)
        hit = by_id.setdefault(
            str(fid),
            {"record": rec, "in_window_dates": [], "all_dates": []},
        )
        hit["in_window_dates"].append((b["date"], b["kind"]))
    return list(by_id.values())
