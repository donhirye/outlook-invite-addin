"""Keyed pseudonymous identifiers (no raw phones in analytics/traces)."""

from __future__ import annotations

import hashlib
import hmac
import os

from app.config import SECRET_KEY


def phone_hash(phone: str) -> str:
    key = (os.getenv("ANALYTICS_HASH_KEY") or SECRET_KEY or "local-dev-key").encode()
    digest = hmac.new(key, (phone or "").encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:24]


def message_fingerprint(message_id: str) -> str:
    if not message_id:
        return ""
    return hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:16]
