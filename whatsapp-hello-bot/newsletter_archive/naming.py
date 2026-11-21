"""Derive issue folder names from the email subject + issue date."""

from __future__ import annotations

import re

_DATE_CHUNK_RE = re.compile(
    r"""(?ix)
    \b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b
    |
    \b(?:January|February|March|April|May|June|July|August|September|October|
       November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)
       \s+\d{1,2}(?:st|nd|rd|th)?(?:,)?\s+\d{4}\b
    |
    \b\d{4}-\d{2}-\d{2}\b
    """
)
_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]+")


def series_slug_from_subject(subject: str) -> str:
    """Stable series slug from the subject (without the date).

    Examples:
      "Crone's Weekly Newsletter" → Crones_Weekly_Newsletter
      "Crone PTSA Newsletter 11.18.2026" → Crone_PTSA_Newsletter
      "Updated Crone PTSA Newsletter March 25, 2026" → Crone_PTSA_Newsletter
    """
    raw = (subject or "").strip()
    lower = raw.lower()

    if "weekly" in lower and "newsletter" in lower:
        return "Crones_Weekly_Newsletter"
    if "ptsa" in lower and "newsletter" in lower:
        return "Crone_PTSA_Newsletter"

    # Generic: strip stated dates, then slugify.
    cleaned = _DATE_CHUNK_RE.sub(" ", raw)
    cleaned = cleaned.replace("'s", "s").replace("’s", "s")
    cleaned = cleaned.replace("&", " and ")
    slug = _NON_ALNUM_RE.sub("_", cleaned).strip("_")
    slug = re.sub(r"_+", "_", slug)
    if not slug:
        slug = "Crone_Newsletter"
    # Keep folder names readable / filesystem-safe.
    return slug[:80].rstrip("_")


def issue_key(series_slug: str, issue_date: str) -> str:
    """Idempotency key so Weekly and PTSA on the same date do not collide."""
    return f"{series_slug}|{issue_date}"


def issue_basename(subject: str, issue_date: str) -> str:
    """Folder / artifact stem: ``<SeriesSlug>_YYYY-MM-DD``."""
    return f"{series_slug_from_subject(subject)}_{issue_date}"
