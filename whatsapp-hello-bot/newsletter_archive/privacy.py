"""Student-PII guards for newsletter → FAQ extraction (offline drafts only)."""

from __future__ import annotations

import re

# Heuristics for student shout-outs / personal details in newsletter prose.
_STUDENT_PII_PATTERNS = (
    re.compile(r"\bpositive referrals?\b", re.I),
    re.compile(r"\bcongratulations to\b", re.I),
    re.compile(r"\bstudent(?:s)? of the (?:month|week|day)\b", re.I),
    re.compile(r"\bhonor roll\b.{0,80}\b(named|includes|congratulat)", re.I),
    # Likely personal phone / student email in body text
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b.{0,40}\bgrade\s*[6-8]\b"),
)


def looks_like_student_pii_content(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    return any(p.search(cleaned) for p in _STUDENT_PII_PATTERNS)


def scrub_or_flag(text: str) -> tuple[str, bool]:
    """Return (text, needs_review). Does not invent replacements for names."""
    if looks_like_student_pii_content(text):
        return text, True
    return text, False
