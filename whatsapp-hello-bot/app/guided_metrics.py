"""Aggregate guided-conversation resolution metrics (no message bodies)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any

from app.config import BASE_DIR, FAQ_GCS_BUCKET

logger = logging.getLogger(__name__)

METRICS_FILE = BASE_DIR / "data" / "guided_metrics.json"
METRICS_GCS_OBJECT = "guided_metrics.json"
_lock = Lock()


def _gcs_enabled() -> bool:
    return bool(FAQ_GCS_BUCKET)


def _empty() -> dict[str, Any]:
    return {
        "guided_started": 0,
        "guided_completed": 0,
        "resolved": 0,
        "partial": 0,
        "unresolved": 0,
        "human_recommended": 0,
        "by_topic": {},
    }


def _load() -> dict[str, Any]:
    if _gcs_enabled():
        try:
            from google.cloud import storage

            blob = storage.Client().bucket(FAQ_GCS_BUCKET).blob(METRICS_GCS_OBJECT)
            if blob.exists():
                data = json.loads(blob.download_as_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {**_empty(), **data}
        except Exception:
            logger.exception("Failed reading guided metrics from GCS")
    if not METRICS_FILE.exists():
        return _empty()
    try:
        data = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {**_empty(), **data}
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed reading %s", METRICS_FILE)
    return _empty()


def _save(data: dict[str, Any]) -> None:
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    METRICS_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if _gcs_enabled():
        try:
            from google.cloud import storage

            blob = storage.Client().bucket(FAQ_GCS_BUCKET).blob(METRICS_GCS_OBJECT)
            blob.upload_from_string(
                json.dumps(data, indent=2) + "\n",
                content_type="application/json",
            )
        except Exception:
            logger.exception("Failed writing guided metrics to GCS")


def _topic_bucket(data: dict[str, Any], topic_id: str) -> dict[str, int]:
    by_topic = data.setdefault("by_topic", {})
    bucket = by_topic.setdefault(
        topic_id,
        {
            "started": 0,
            "completed": 0,
            "resolved": 0,
            "partial": 0,
            "unresolved": 0,
            "human_recommended": 0,
        },
    )
    return bucket


def record_guided_start(topic_id: str) -> None:
    with _lock:
        data = _load()
        data["guided_started"] = int(data.get("guided_started") or 0) + 1
        bucket = _topic_bucket(data, topic_id)
        bucket["started"] = int(bucket.get("started") or 0) + 1
        _save(data)


def record_resolution(
    topic_id: str,
    outcome: str,
    *,
    human_recommended: bool = False,
) -> None:
    key = (outcome or "").strip().lower()
    if key not in {"resolved", "partial", "unresolved"}:
        key = "unresolved"
    with _lock:
        data = _load()
        data["guided_completed"] = int(data.get("guided_completed") or 0) + 1
        data[key] = int(data.get(key) or 0) + 1
        if human_recommended:
            data["human_recommended"] = int(data.get("human_recommended") or 0) + 1
        bucket = _topic_bucket(data, topic_id)
        bucket["completed"] = int(bucket.get("completed") or 0) + 1
        bucket[key] = int(bucket.get(key) or 0) + 1
        if human_recommended:
            bucket["human_recommended"] = int(bucket.get("human_recommended") or 0) + 1
        _save(data)


def get_guided_metrics() -> dict[str, Any]:
    with _lock:
        data = _load()
        started = int(data.get("guided_started") or 0)
        completed = int(data.get("guided_completed") or 0)
        resolved = int(data.get("resolved") or 0)
        partial = int(data.get("partial") or 0)
        unresolved = int(data.get("unresolved") or 0)
        return {
            "guided_started": started,
            "guided_completed": completed,
            "resolved": resolved,
            "partial": partial,
            "unresolved": unresolved,
            "human_recommended": int(data.get("human_recommended") or 0),
            "completion_rate": round(completed / started, 3) if started else 0.0,
            "resolution_rate": round(resolved / completed, 3) if completed else 0.0,
            "partial_rate": round(partial / completed, 3) if completed else 0.0,
            "unresolved_rate": round(unresolved / completed, 3) if completed else 0.0,
            "by_topic": data.get("by_topic") or {},
        }
