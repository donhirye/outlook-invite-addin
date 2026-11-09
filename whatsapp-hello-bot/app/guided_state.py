"""Per-parent guided conversation state + webhook dedupe."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from threading import Lock
from typing import Any

from app.config import BASE_DIR, FAQ_GCS_BUCKET

logger = logging.getLogger(__name__)

STATE_FILE = BASE_DIR / "data" / "guided_state.json"
SEEN_FILE = BASE_DIR / "data" / "webhook_seen.json"
STATE_GCS_OBJECT = "guided_state.json"
SEEN_GCS_OBJECT = "webhook_seen.json"
STATE_TTL_SECONDS = 24 * 60 * 60
SEEN_TTL_SECONDS = 2 * 60 * 60

_lock = Lock()


def _gcs_enabled() -> bool:
    return bool(FAQ_GCS_BUCKET)


def _empty_state_doc() -> dict[str, Any]:
    return {"sessions": {}}


def _empty_seen_doc() -> dict[str, Any]:
    return {"ids": {}}


def _load_json(path: Path, empty: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed reading %s", path)
    return empty


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _load_gcs(object_name: str, empty: dict[str, Any]) -> dict[str, Any] | None:
    if not _gcs_enabled():
        return None
    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(FAQ_GCS_BUCKET).blob(object_name)
    if not blob.exists():
        return None
    try:
        data = json.loads(blob.download_as_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed reading gs://%s/%s", FAQ_GCS_BUCKET, object_name)
    return empty


def _save_gcs(object_name: str, data: dict[str, Any]) -> None:
    if not _gcs_enabled():
        return
    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(FAQ_GCS_BUCKET).blob(object_name)
    blob.upload_from_string(
        json.dumps(data, indent=2) + "\n",
        content_type="application/json",
    )


def _prune_sessions(sessions: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    kept = {}
    for phone, session in sessions.items():
        if not isinstance(session, dict):
            continue
        updated = float(session.get("updated_at") or 0)
        if now - updated <= STATE_TTL_SECONDS:
            kept[phone] = session
    return kept


def _prune_seen(ids: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    return {
        mid: ts
        for mid, ts in ids.items()
        if isinstance(ts, (int, float)) and now - float(ts) <= SEEN_TTL_SECONDS
    }


def get_session(phone: str) -> dict[str, Any] | None:
    key = (phone or "").strip()
    if not key:
        return None
    with _lock:
        doc = _load_gcs(STATE_GCS_OBJECT, _empty_state_doc()) or _load_json(
            STATE_FILE, _empty_state_doc()
        )
        sessions = _prune_sessions(doc.get("sessions") or {})
        session = sessions.get(key)
        return dict(session) if isinstance(session, dict) else None


def set_session(phone: str, session: dict[str, Any] | None) -> None:
    key = (phone or "").strip()
    if not key:
        return
    with _lock:
        doc = _load_gcs(STATE_GCS_OBJECT, _empty_state_doc()) or _load_json(
            STATE_FILE, _empty_state_doc()
        )
        sessions = _prune_sessions(doc.get("sessions") or {})
        if session is None:
            sessions.pop(key, None)
        else:
            payload = dict(session)
            payload["updated_at"] = time.time()
            sessions[key] = payload
        doc = {"sessions": sessions}
        _save_json(STATE_FILE, doc)
        _save_gcs(STATE_GCS_OBJECT, doc)


def clear_session(phone: str) -> None:
    set_session(phone, None)


def already_seen_message(message_id: str) -> bool:
    mid = (message_id or "").strip()
    if not mid:
        return False
    with _lock:
        doc = _load_gcs(SEEN_GCS_OBJECT, _empty_seen_doc()) or _load_json(
            SEEN_FILE, _empty_seen_doc()
        )
        ids = _prune_seen(doc.get("ids") or {})
        if mid in ids:
            return True
        ids[mid] = time.time()
        out = {"ids": ids}
        _save_json(SEEN_FILE, out)
        _save_gcs(SEEN_GCS_OBJECT, out)
        return False
