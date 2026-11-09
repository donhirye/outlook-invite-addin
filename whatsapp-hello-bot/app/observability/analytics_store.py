"""Durable analytics event log (local JSONL + optional GCS mirror)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.config import BASE_DIR, FAQ_GCS_BUCKET

logger = logging.getLogger(__name__)

EVENTS_FILE = BASE_DIR / "data" / "analytics_events.jsonl"
EVENTS_GCS_OBJECT = "analytics_events.jsonl"
SESSION_IDLE_MINUTES = 30
ABANDON_IDLE_MINUTES = 30

_lock = Lock()


def _gcs_enabled() -> bool:
    return bool(FAQ_GCS_BUCKET)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def append_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = dict(event)
    payload.setdefault("event_id", str(uuid.uuid4()))
    payload.setdefault("ts", _now().isoformat())
    line = json.dumps(payload, ensure_ascii=False)
    with _lock:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with EVENTS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        if _gcs_enabled():
            try:
                from google.cloud import storage

                blob = storage.Client().bucket(FAQ_GCS_BUCKET).blob(EVENTS_GCS_OBJECT)
                # Append-safe enough for single min-instance; multi-instance may race.
                existing = ""
                if blob.exists():
                    existing = blob.download_as_text(encoding="utf-8")
                blob.upload_from_string(
                    existing + line + "\n",
                    content_type="application/x-ndjson",
                )
            except Exception:
                logger.exception("Failed mirroring analytics event to GCS")
    return payload


def load_events(*, since_days: int | None = 30) -> list[dict[str, Any]]:
    lines: list[str] = []
    if _gcs_enabled():
        try:
            from google.cloud import storage

            blob = storage.Client().bucket(FAQ_GCS_BUCKET).blob(EVENTS_GCS_OBJECT)
            if blob.exists():
                lines = blob.download_as_text(encoding="utf-8").splitlines()
        except Exception:
            logger.exception("Failed loading analytics events from GCS")
    if not lines and EVENTS_FILE.exists():
        lines = EVENTS_FILE.read_text(encoding="utf-8").splitlines()

    cutoff = None
    if since_days is not None:
        cutoff = _now() - timedelta(days=since_days)

    events: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if cutoff is not None:
            try:
                ts = datetime.fromisoformat(str(obj.get("ts")).replace("Z", "+00:00"))
                if ts < cutoff:
                    continue
            except Exception:
                pass
        events.append(obj)
    return events


def sessionize(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign session ids using 30 minutes inactivity per user_hash."""
    idle = timedelta(minutes=SESSION_IDLE_MINUTES)
    last_ts: dict[str, datetime] = {}
    last_session: dict[str, str] = {}
    out = []
    for ev in sorted(events, key=lambda e: str(e.get("ts") or "")):
        user = str(ev.get("user_hash") or "unknown")
        try:
            ts = datetime.fromisoformat(str(ev.get("ts")).replace("Z", "+00:00"))
        except Exception:
            ts = _now()
        prev = last_ts.get(user)
        if not prev or (ts - prev) > idle:
            sess = f"{user}-{int(ts.timestamp())}"
            last_session[user] = sess
        last_ts[user] = ts
        cloned = dict(ev)
        cloned["session_id"] = last_session[user]
        out.append(cloned)
    return out
