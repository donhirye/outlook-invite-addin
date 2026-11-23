"""Date-list / 'what's going on' overview: calendar + per-date FAQ bullets."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from app.calendar_service import is_faq_action_question
from app.calendar_store import list_events, parse_iso_date
from app.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_REASONING_EFFORT
from app.faq_records import chicago_today, list_records

logger = logging.getLogger(__name__)

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

# Parent asks that need LLM (or rule) reshape of the retrieved month list.
_RESHAPE_RE = re.compile(
    r"\b("
    r"deadlines?|due\s+dates?|"
    r"skip\b.{0,40}\bsports?\b|"
    r"\bsports?\b.{0,40}\b(skip|without|off)|"
    r"without\s+sports?|except\s+sports?|excluding\s+sports?|no\s+sports?|"
    r"non[\s-]?sports?|"
    r"only\s+(deadlines?|sports?|concerts?|music|trips?)|"
    r"just\s+(the\s+)?(deadlines?|sports?|concerts?)|"
    r"sports?\s+events?|athletics?|"
    r"basketball|wrestling|soccer|volleyball|football|cross\s*country|"
    r"concerts?\s+only|music\s+only|field\s+trips?"
    r")\b",
    re.I,
)
_SPORTS_LINE_RE = re.compile(
    r"\b("
    r"basketball|wrestling|soccer|volleyball|football|athletics?|"
    r"cross\s*country|vs\.?|against|7[ah]|8[ah]|meet|meets|game|games"
    r")\b",
    re.I,
)
_DEADLINE_ASK_RE = re.compile(r"\b(deadlines?|due\s+dates?)\b", re.I)

_OVERVIEW_RESHAPE_INSTRUCTIONS = """You filter and rewrite a parent-facing monthly events list.
You are given ONLY the EVIDENCE bullets (already retrieved for the date window).
RULES:
1. Use ONLY facts from EVIDENCE. Do not invent dates, events, opponents, or deadlines.
2. Follow the parent's instructions (e.g. deadlines only, skip sports).
3. Keep a short bullet list. One line per kept item with the date when known.
4. If nothing in EVIDENCE matches the filter, say so briefly and suggest asking without the filter.
5. Do not add a Source: line.
6. Reply with plain text only (bullets OK)."""


def needs_overview_reshape(text: str) -> bool:
    """True when the ask filters/reshapes the month list (not a plain dump)."""
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    return bool(_RESHAPE_RE.search(cleaned))


def _is_sports_evidence_line(line: str) -> bool:
    return bool(_SPORTS_LINE_RE.search(line or ""))

def is_overview_question(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned or is_faq_action_question(cleaned):
        return False
    month_re = r"(" + "|".join(_MONTHS) + r")"
    has_month = bool(re.search(rf"\b{month_re}\b", cleaned, re.I))
    if _OVERVIEW_CUES.search(cleaned):
        return True
    # "events/happening/going on … December"
    if re.search(
        rf"\b(events?|happen\w*|going\s+on)\b.*\b{month_re}\b",
        cleaned,
        re.I,
    ):
        return True
    if re.search(
        rf"\b{month_re}\b.*\b(events?|happen\w*|going\s+on)\b",
        cleaned,
        re.I,
    ):
        return True
    # Typo-tolerant: "whats ahppening in december" — what/whats + month
    if has_month and re.search(r"\b(what|whats|what's|anything)\b", cleaned, re.I):
        return True
    return False


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
    """Strict per-date FAQ bullets inside [start, end] only (no related follow-ups)."""
    del today  # kept for call-site compat; overview no longer uses as-of filtering here
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
            bullets.append(
                {
                    "date": snip["date"],
                    "kind": snip["kind"],
                    "blurb": _short_blurb(snip["clause"], snip["date"]),
                    "record": rec,
                }
            )

    bullets.sort(key=lambda b: (b["date"], b["record"].get("faq_id") or ""))
    return bullets


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
    return f"• {b['date'].isoformat()} ({kind}) — {b['blurb']}"


def _build_overview_evidence(
    start: date,
    end: date,
    *,
    today: date | None = None,
) -> tuple[list[str], list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (display_sections_without_header, chunks, cal_events, faq_bullets)."""
    cal = calendar_events_in_window(start, end)
    faq_bullets = faq_date_bullets_in_window(start, end, today=today)
    chunks: list[str] = []
    sections: list[str] = []

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

    return sections, chunks, cal, faq_bullets


def _rule_reshape_overview(
    question: str,
    *,
    cal: list[dict[str, Any]],
    faq_bullets: list[dict[str, Any]],
    start: date,
    end: date,
) -> str:
    """Deterministic filter when LLM reshape is unavailable."""
    want_deadlines = bool(_DEADLINE_ASK_RE.search(question or ""))
    skip_sports = bool(
        re.search(r"\b(skip|without|except|excluding|no)\b.*\bsports?\b", question or "", re.I)
        or re.search(r"\bsports?\b.*\b(skip|without|off|out)\b", question or "", re.I)
    )
    # "what deadlines" implies deadlines focus even without "skip sports"
    lines = [f"*What's going on ({start.isoformat()} → {end.isoformat()})*"]
    kept_cal: list[str] = []
    if not want_deadlines:
        for ev in cal:
            line = _fmt_cal_line(ev)
            if skip_sports and _is_sports_evidence_line(line):
                continue
            kept_cal.append(line)
    kept_faq: list[str] = []
    for b in faq_bullets:
        if want_deadlines and b.get("kind") != "deadline":
            continue
        line = _fmt_faq_bullet(b)
        if skip_sports and _is_sports_evidence_line(line):
            continue
        kept_faq.append(line)
    if kept_cal:
        lines.append("*School / PTSA calendar*")
        lines.extend(kept_cal)
    if kept_faq:
        lines.append("*PTSA announcements & deadlines (from FAQ)*")
        lines.extend(kept_faq)
    if not kept_cal and not kept_faq:
        lines.append(
            "Nothing in this date window matched that filter. "
            "Try asking without the filter, or ask about a specific event."
        )
    return "\n".join(lines)


def reshape_overview_with_llm(
    question: str,
    evidence_lines: list[str],
    *,
    start: date,
    end: date,
) -> tuple[str | None, dict[str, Any]]:
    """LLM reshapes retrieved bullets only. Returns (answer, usage_meta)."""
    usage: dict[str, Any] = {
        "llm_invocations": 0,
        "model": None,
        "input_tokens": None,
        "output_tokens": None,
    }
    if not OPENAI_API_KEY:
        return None, usage
    if not evidence_lines:
        return (
            "I couldn't find calendar events or dated FAQ items in that window.",
            usage,
        )
    numbered = "\n".join(f"{i+1}. {line}" for i, line in enumerate(evidence_lines))
    user_input = (
        f"DATE WINDOW: {start.isoformat()} → {end.isoformat()}\n"
        f"TODAY (America/Chicago): {chicago_today().isoformat()}\n\n"
        f"EVIDENCE:\n{numbered}\n\n"
        f"PARENT QUESTION:\n{question.strip()}"
    )
    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
        create_kwargs: dict[str, Any] = {
            "model": OPENAI_MODEL,
            "instructions": _OVERVIEW_RESHAPE_INSTRUCTIONS,
            "input": user_input,
            "temperature": 0,
        }
        if OPENAI_REASONING_EFFORT:
            create_kwargs["reasoning"] = {"effort": OPENAI_REASONING_EFFORT}
        try:
            response = client.responses.create(**create_kwargs)
        except Exception as exc:
            msg = str(exc).lower()
            retried = False
            if "temperature" in msg and "temperature" in create_kwargs:
                create_kwargs.pop("temperature", None)
                retried = True
            if "reasoning" in msg and "reasoning" in create_kwargs:
                create_kwargs.pop("reasoning", None)
                retried = True
            if not retried:
                raise
            response = client.responses.create(**create_kwargs)
        usage["llm_invocations"] = 1
        usage["model"] = OPENAI_MODEL
        u = getattr(response, "usage", None)
        usage["input_tokens"] = getattr(u, "input_tokens", None)
        usage["output_tokens"] = getattr(u, "output_tokens", None)
        text = (getattr(response, "output_text", None) or "").strip()
        if not text:
            # Fallback extract
            for item in getattr(response, "output", None) or []:
                for part in getattr(item, "content", None) or []:
                    t = getattr(part, "text", None)
                    if t:
                        text = str(t).strip()
                        break
        return (text or None), usage
    except Exception:
        logger.exception("Overview LLM reshape failed")
        return None, usage


def answer_overview(
    text: str,
    *,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Retrieve month evidence; dump directly, or LLM/rule-reshape when filtered."""
    if not is_overview_question(text):
        return None
    today = today or chicago_today()
    start, end = parse_date_window(text, today=today)
    sections, chunks, cal, faq_bullets = _build_overview_evidence(
        start, end, today=today
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

    base = {
        "route": "overview",
        "intent": "overview",
        "sources": ["school_calendar", "faq_records"],
        "source_name": "; ".join(source_names) if source_names else None,
        "source_url": None,
        "retrieved_chunks": chunks,
        "faq_id": None,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "llm_invocations": 0,
        "model": None,
        "input_tokens": None,
        "output_tokens": None,
    }

    if not cal and not faq_bullets:
        return {
            **base,
            "messages": [
                "I couldn't find calendar events or dated FAQ items in that window. "
                "Please check the school calendar or ask PTSA Administrators."
            ],
            "retrieval_mode": "overview",
            "answer_outcome": "unanswered",
        }

    header = f"*What's going on ({start.isoformat()} → {end.isoformat()})*"
    dump = "\n".join([header, *sections])

    if not needs_overview_reshape(text):
        return {
            **base,
            "messages": [dump],
            "retrieval_mode": "overview",
            "answer_outcome": "answered",
        }

    # Filtered ask: reshape from retrieved evidence only (LLM, else rules).
    evidence_for_llm = [ln for ln in sections if ln.startswith("• ")]
    reshaped, usage = reshape_overview_with_llm(
        text, evidence_for_llm, start=start, end=end
    )
    if reshaped:
        return {
            **base,
            "messages": [reshaped],
            "retrieval_mode": "overview_llm",
            "answer_outcome": "answered",
            "llm_invocations": usage.get("llm_invocations") or 1,
            "model": usage.get("model"),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }

    rule_text = _rule_reshape_overview(
        text, cal=cal, faq_bullets=faq_bullets, start=start, end=end
    )
    return {
        **base,
        "messages": [rule_text],
        "retrieval_mode": "overview",
        "answer_outcome": "answered",
        "fallback": "overview_rule_reshape",
    }


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
