"""Content hashing for idempotent newsletter archives."""

from __future__ import annotations

import hashlib
import re


_WS_RE = re.compile(r"\s+")


def normalize_html_for_hash(html: str) -> str:
    """Normalize HTML so trivial whitespace diffs do not change the hash."""
    text = (html or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text).strip().lower()
    return text


def content_hash(html: str) -> str:
    payload = normalize_html_for_hash(html).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
