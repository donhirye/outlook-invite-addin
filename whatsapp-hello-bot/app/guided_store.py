"""Admin-approved guided conversation topic packs."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import BASE_DIR, FAQ_GCS_BUCKET

logger = logging.getLogger(__name__)

GUIDED_DIR = BASE_DIR / "data" / "guided"
GUIDED_GCS_PREFIX = "guided/"


def _gcs_enabled() -> bool:
    return bool(FAQ_GCS_BUCKET)


def _topic_path(topic_id: str) -> Path:
    safe = "".join(ch for ch in topic_id if ch.isalnum() or ch in {"_", "-"})
    return GUIDED_DIR / f"{safe}.json"


def _validate_topic(data: dict[str, Any]) -> dict[str, Any]:
    topic_id = str(data.get("id") or "").strip()
    if not topic_id:
        raise ValueError("Topic id is required")
    title = str(data.get("title") or topic_id).strip()
    steps = data.get("steps") or {}
    if not isinstance(steps, dict) or not steps:
        raise ValueError("Topic must include steps")
    start = str(data.get("start_step") or "").strip()
    if start not in steps:
        raise ValueError(f"start_step '{start}' missing from steps")
    triggers = data.get("triggers") or []
    if not isinstance(triggers, list):
        raise ValueError("triggers must be a list")
    deadlines = data.get("deadlines") or {}
    if not isinstance(deadlines, dict):
        raise ValueError("deadlines must be an object map")
    return {
        "id": topic_id,
        "title": title,
        "enabled": bool(data.get("enabled", True)),
        "priority": int(data.get("priority") or 100),
        "triggers": [str(t).strip() for t in triggers if str(t).strip()],
        "start_step": start,
        "escalation": str(data.get("escalation") or "").strip(),
        "steps": steps,
        "deadlines": {
            str(k).strip(): str(v).strip()
            for k, v in deadlines.items()
            if str(k).strip() and str(v).strip()
        },
    }


def _read_local_topic(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _validate_topic(data)
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        logger.exception("Failed reading guided topic %s", path)
        return None


def _write_local_topic(topic: dict[str, Any]) -> None:
    path = _topic_path(topic["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(topic, indent=2) + "\n", encoding="utf-8")


def _write_gcs_topic(topic: dict[str, Any]) -> None:
    if not _gcs_enabled():
        return
    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(FAQ_GCS_BUCKET).blob(f"{GUIDED_GCS_PREFIX}{topic['id']}.json")
    blob.upload_from_string(
        json.dumps(topic, indent=2) + "\n",
        content_type="application/json",
    )


def _read_gcs_topic(topic_id: str) -> dict[str, Any] | None:
    if not _gcs_enabled():
        return None
    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(FAQ_GCS_BUCKET).blob(f"{GUIDED_GCS_PREFIX}{topic_id}.json")
    if not blob.exists():
        return None
    try:
        data = json.loads(blob.download_as_text(encoding="utf-8"))
        return _validate_topic(data)
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        logger.exception("Failed reading gs://%s/%s%s.json", FAQ_GCS_BUCKET, GUIDED_GCS_PREFIX, topic_id)
        return None


def list_local_topic_ids() -> list[str]:
    if not GUIDED_DIR.exists():
        return []
    return sorted(p.stem for p in GUIDED_DIR.glob("*.json"))


def get_topic(topic_id: str) -> dict[str, Any] | None:
    gcs_topic = _read_gcs_topic(topic_id)
    if gcs_topic:
        return gcs_topic
    return _read_local_topic(_topic_path(topic_id))


def list_topics(*, enabled_only: bool = False) -> list[dict[str, Any]]:
    ids = set(list_local_topic_ids())
    if _gcs_enabled():
        try:
            from google.cloud import storage

            client = storage.Client()
            bucket = client.bucket(FAQ_GCS_BUCKET)
            for blob in bucket.list_blobs(prefix=GUIDED_GCS_PREFIX):
                name = blob.name[len(GUIDED_GCS_PREFIX) :]
                if name.endswith(".json"):
                    ids.add(name[: -len(".json")])
        except Exception:
            logger.exception("Failed listing guided topics from GCS")

    topics: list[dict[str, Any]] = []
    for topic_id in sorted(ids):
        topic = get_topic(topic_id)
        if not topic:
            continue
        if enabled_only and not topic.get("enabled", True):
            continue
        topics.append(topic)
    topics.sort(key=lambda t: (int(t.get("priority") or 100), t.get("title") or t["id"]))
    return topics


def set_topic(raw: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(raw, str):
        data = json.loads(raw)
    else:
        data = raw
    topic = _validate_topic(data)
    _write_local_topic(topic)
    _write_gcs_topic(topic)
    return topic


def set_topic_enabled(topic_id: str, enabled: bool) -> dict[str, Any]:
    topic = get_topic(topic_id)
    if not topic:
        raise ValueError(f"Unknown topic: {topic_id}")
    topic["enabled"] = bool(enabled)
    return set_topic(topic)


def guided_storage_label() -> str:
    if _gcs_enabled():
        return f"gs://{FAQ_GCS_BUCKET}/{GUIDED_GCS_PREFIX}"
    return str(GUIDED_DIR)
