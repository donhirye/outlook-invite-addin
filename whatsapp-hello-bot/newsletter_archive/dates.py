"""Publication / issue date detection for newsletter messages."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from newsletter_archive.models import DateBasis

_MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
)

# Parser rules (in order within each text blob):
# 1) Month name + day + year  — "November 20, 2026" / "20 November 2026"
# 2) ISO  — "2026-11-20"
# 3) Numeric with dots  — "11.11.2026" / "11.11.26"  (common in Crone PTSA subjects)
# 4) Numeric with slashes — "11/11/2026" / "11/11/26"
#
# Issue-date resolution prefers a *single* date found in the subject line over
# dates in the body (bodies often mention many event dates).
_DATE_PATTERNS = [
    re.compile(
        rf"\b(?P<month>{_MONTH})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:,)?\s+"
        rf"(?P<year>\d{{4}})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{_MONTH})\s+"
        rf"(?P<year>\d{{4}})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b"),
    # 11.11.2026 or 11.11.26 (Crone PTSA subject style)
    re.compile(
        r"\b(?P<month>\d{1,2})\.(?P<day>\d{1,2})\.(?P<year>\d{4}|\d{2})\b"
    ),
    # 11/11/2026 or 11/11/26
    re.compile(
        r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4}|\d{2})\b"
    ),
]

_MONTH_NUM = {
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
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def _month_to_int(value: str) -> int | None:
    if value.isdigit():
        n = int(value)
        return n if 1 <= n <= 12 else None
    return _MONTH_NUM.get(value.lower())


def _year_to_int(value: str) -> int | None:
    """Accept 4-digit years, or 2-digit years as 2000–2099."""
    if not value.isdigit():
        return None
    year = int(value)
    if len(value) == 2:
        year += 2000
    if 1990 <= year <= 2100:
        return year
    return None


def parse_stated_date(text: str) -> list[str]:
    """Return unique ISO dates (YYYY-MM-DD) found in text, in discovery order."""
    found: list[str] = []
    seen: set[str] = set()
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text or ""):
            gd = match.groupdict()
            month = _month_to_int(gd["month"])
            day = int(gd["day"])
            year = _year_to_int(gd["year"])
            if month is None or year is None:
                continue
            try:
                iso = datetime(year, month, day, tzinfo=timezone.utc).date().isoformat()
            except ValueError:
                continue
            if iso not in seen:
                seen.add(iso)
                found.append(iso)
    return found


def received_iso_from_internal_ms(internal_ms: str | int) -> str:
    ms = int(internal_ms)
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def received_iso_from_date_header(date_header: str | None) -> str | None:
    if not date_header:
        return None
    try:
        dt = parsedate_to_datetime(date_header)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def resolve_issue_date(
    *,
    subject: str,
    body_text: str,
    received_at_iso: str,
) -> tuple[str | None, DateBasis, list[str]]:
    """Prefer a clearly stated publication date; else email received date.

    Returns (issue_date, basis, flags). issue_date is None when ambiguous.

    Rules:
    - If the subject contains exactly one parseable date, use it (ignore body
      event dates for folder naming).
    - If the subject has multiple distinct dates, flag ambiguous.
    - Else if the body head has exactly one date, use it.
    - Else if the body has multiple dates, flag ambiguous.
    - Else fall back to the email received calendar day (UTC).
    """
    flags: list[str] = []
    subject_dates = parse_stated_date(subject)
    if len(subject_dates) == 1:
        return subject_dates[0], DateBasis.PUBLICATION_STATED, flags
    if len(subject_dates) > 1:
        flags.append(f"ambiguous_subject_dates:{','.join(subject_dates)}")
        return None, DateBasis.AMBIGUOUS, flags

    body_head = (body_text or "")[:4000]
    body_dates = parse_stated_date(body_head)
    if len(body_dates) == 1:
        flags.append("publication_date_from_body")
        return body_dates[0], DateBasis.PUBLICATION_STATED, flags
    if len(body_dates) > 1:
        flags.append(f"ambiguous_body_dates:{','.join(body_dates)}")
        return None, DateBasis.AMBIGUOUS, flags

    try:
        received_day = received_at_iso[:10]
        datetime.strptime(received_day, "%Y-%m-%d")
    except (TypeError, ValueError):
        flags.append("unparseable_received_at")
        return None, DateBasis.AMBIGUOUS, flags

    flags.append("used_email_received_date")
    return received_day, DateBasis.EMAIL_RECEIVED, flags
