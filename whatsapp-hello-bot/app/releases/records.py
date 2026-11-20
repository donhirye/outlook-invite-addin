"""Read deployment records written by deploy scripts (never secrets)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import SHARED_DATA_DIR

logger = logging.getLogger(__name__)

RELEASES_DIR = SHARED_DATA_DIR / "releases"
STAGING_RECORD = RELEASES_DIR / "staging-latest.json"
PRODUCTION_RECORD = RELEASES_DIR / "production-latest.json"


def _read_record(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "available": False,
            "source": "recorded",
            "status": "Unknown",
            "detail": f"No record at {path.name}",
        }
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
    return {
        "available": True,
        "source": "recorded",
        "status": "Recorded",
        "git_sha": (data.get("git_sha") or "").strip() or None,
        "branch": (data.get("branch") or "").strip() or None,
        "revision": (data.get("revision") or "").strip() or None,
        "image": (data.get("image") or "").strip() or None,
        "url": (data.get("url") or "").strip() or None,
        "deployed_at": (data.get("deployed_at") or "").strip() or None,
        "smoke_ok": data.get("smoke_ok"),
        "service": (data.get("service") or "").strip() or None,
        "project": (data.get("project") or "").strip() or None,
        "raw": data,
    }


def load_staging_record() -> dict[str, Any]:
    return _read_record(STAGING_RECORD)


def load_production_record() -> dict[str, Any]:
    return _read_record(PRODUCTION_RECORD)
