"""PTSA student-privacy gate (deterministic; runs before FAQ/calendar)."""

from __future__ import annotations

import re

from app.config import STUDENT_PRIVACY_MESSAGE

# Asks for a specific student's identifiers — not general policy FAQs
# (e.g. "how much is a replacement student ID?" should still pass).
_PRIVACY_PATTERNS = (
    # Student ID / school ID for a person
    r"\b(student\s*id|school\s*id)\b.{0,50}\b(for|of|belonging to|under)\b",
    r"\b(for|of|belonging to)\b.{0,50}\b(student\s*id|school\s*id)\b",
    r"\b(look\s*up|find|get|give me|what(?:'s| is)|tell me|share|provide)\b"
    r".{0,50}\b(student\s*id|school\s*id)\b",
    r"\b(student\s*id|school\s*id)\s*(number|#)?\s*(is|for)\b",
    # Phone / email tied to a student or child
    r"\b(student|child(?:'s)?|kid(?:'s)?)\b.{0,40}\b(phone|cell|mobile|email|e-?mail)\b",
    r"\b(phone|cell|mobile|email|e-?mail)\b.{0,40}\b(student|child|kid)\b",
    r"\b(look\s*up|find|get|give me|what(?:'s| is)|tell me)\b.{0,40}"
    r"\b(student|child(?:'s)?)\b.{0,20}\b(phone|cell|mobile|email|e-?mail)\b",
    # Particular student by name / personal info request
    r"\bstudent\s+named\b",
    r"\b(particular|specific)\s+student\b.{0,40}\b(name|id|phone|email|info|information)\b",
    r"\b(name|id|phone|email|info|information)\b.{0,40}\b(particular|specific)\s+student\b",
    r"\b(personal\s+information|pii)\b.{0,40}\b(student|child|kid)\b",
    r"\b(student|child|kid)\b.{0,40}\b(personal\s+information|pii)\b",
    r"\binformation about (a |the )?(student|child)\b",
)


def looks_like_student_pii_request(text: str) -> bool:
    """True when the parent appears to ask for a student's personal identifiers."""
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return False
    return any(re.search(pat, cleaned, flags=re.IGNORECASE) for pat in _PRIVACY_PATTERNS)


def privacy_reply_if_needed(text: str) -> str | None:
    """Return the policy message when blocked; otherwise None."""
    if looks_like_student_pii_request(text):
        return STUDENT_PRIVACY_MESSAGE
    return None
