"""Read deployment records written by deploy scripts (never secrets).

Looks locally under data/releases/, then (on Cloud Run) at GCS
gs://{FAQ_GCS_BUCKET}/releases/{staging|production}-latest.json.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import FAQ_GCS_BUCKET, SHARED_DATA_DIR

logger = logging.getLogger(__name__)

RELEASES_DIR = SHARED_DATA_DIR / "releases"
STAGING_RECORD = RELEASES_DIR / "staging-latest.json"
PRODUCTION_RECORD = RELEASES_DIR / "production-latest.json"
GCS_RELEASES_PREFIX = "releases"


def _normalize(data: dict[str, Any], *, source: str, detail: str | None = None) -> dict[str, Any]:
    return {
        "available": True,
        "source": source,
        "status": "Recorded",
        "detail": detail,
        "git_sha": (data.get("git_sha") or "").strip() or None,
        "branch": (data.get("branch") or "").strip() or None,
        "revision": (data.get("revision") or "").strip() or None,
        "image": (data.get("image") or "").strip() or None,
        "url": (data.get("url") or "").strip() or None,
        "deployed_at": (data.get("deployed_at") or "").strip() or None,
        "smoke_ok": data.get("smoke_ok"),
        "service": (data.get("service") or "").strip() or None,
        "project": (data.get("project") or "").strip() or None,
        "faq_gcs_prefix": (data.get("faq_gcs_prefix") or "").strip() or None,
        "raw": data,
    }


def _missing(path_name: str) -> dict[str, Any]:
    return {
        "available": False,
        "source": "recorded",
        "status": "Unknown",
        "detail": f"No record at {path_name}",
    }


def _read_local(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Bad release record %s: %s", path, exc)
        return {
            "available": False,
            "source": "recorded",
            "status": "Unknown",
            "detail": f"Could not parse {path.name}",
        }
    if not isinstance(data, dict):
        return {
            "available": False,
            "source": "recorded",
            "status": "Unknown",
            "detail": "Record is not an object",
        }
    return _normalize(data, source="recorded")


def _read_gcs(object_name: str) -> dict[str, Any] | None:
    if not FAQ_GCS_BUCKET:
        return None
    try:
        from google.cloud import storage  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.debug("GCS client unavailable for release records: %s", exc)
        return None
    try:
        blob = storage.Client().bucket(FAQ_GCS_BUCKET).blob(object_name)
        if not blob.exists():
            return None
        data = json.loads(blob.download_as_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("GCS release record %s failed: %s", object_name, exc)
        return None
    if not isinstance(data, dict):
        return None
    return _normalize(data, source="gcs", detail=f"gs://{FAQ_GCS_BUCKET}/{object_name}")


def _read_record(path: Path, gcs_object: str) -> dict[str, Any]:
    local = _read_local(path)
    if local is not None:
        return local
    gcs = _read_gcs(gcs_object)
    if gcs is not None:
        return gcs
    return _missing(path.name)


def load_staging_record() -> dict[str, Any]:
    return _read_record(STAGING_RECORD, f"{GCS_RELEASES_PREFIX}/staging-latest.json")


def load_production_record() -> dict[str, Any]:
    return _read_record(PRODUCTION_RECORD, f"{GCS_RELEASES_PREFIX}/production-latest.json")
