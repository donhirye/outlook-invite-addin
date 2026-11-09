"""Admin-selected answering engine (manual experiment control)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import BASE_DIR, FAQ_GCS_BUCKET
from app.engines.base import ENGINE_1, IMPLEMENTED_ENGINES

logger = logging.getLogger(__name__)

CONFIG_FILE = BASE_DIR / "data" / "engine_config.json"
CONFIG_GCS_OBJECT = "engine_config.json"


def _gcs_enabled() -> bool:
    return bool(FAQ_GCS_BUCKET)


def _default() -> dict:
    return {"selected_engine": ENGINE_1, "pinned_sessions": {}}


def _load() -> dict:
    if _gcs_enabled():
        try:
            from google.cloud import storage

            blob = storage.Client().bucket(FAQ_GCS_BUCKET).blob(CONFIG_GCS_OBJECT)
            if blob.exists():
                data = json.loads(blob.download_as_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {**_default(), **data}
        except Exception:
            logger.exception("Failed reading engine config from GCS")
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**_default(), **data}
        except (json.JSONDecodeError, OSError):
            logger.exception("Failed reading %s", CONFIG_FILE)
    return _default()


def _save(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if _gcs_enabled():
        try:
            from google.cloud import storage

            blob = storage.Client().bucket(FAQ_GCS_BUCKET).blob(CONFIG_GCS_OBJECT)
            blob.upload_from_string(
                json.dumps(data, indent=2) + "\n",
                content_type="application/json",
            )
        except Exception:
            logger.exception("Failed writing engine config to GCS")


def get_selected_engine_id() -> str:
    eid = str((_load().get("selected_engine") or ENGINE_1)).strip()
    if eid not in IMPLEMENTED_ENGINES:
        return ENGINE_1
    return eid


def set_selected_engine_id(engine_id: str) -> str:
    eid = (engine_id or "").strip()
    if eid not in IMPLEMENTED_ENGINES:
        raise ValueError(f"Engine not selectable: {engine_id}")
    data = _load()
    data["selected_engine"] = eid
    _save(data)
    return eid


def get_pinned_engine(phone: str) -> str | None:
    pins = _load().get("pinned_sessions") or {}
    val = pins.get((phone or "").strip())
    return str(val) if val else None


def pin_engine(phone: str, engine_id: str) -> None:
    data = _load()
    pins = dict(data.get("pinned_sessions") or {})
    pins[(phone or "").strip()] = engine_id
    # Bound growth
    if len(pins) > 5000:
        pins = dict(list(pins.items())[-2500:])
    data["pinned_sessions"] = pins
    _save(data)


def clear_pin(phone: str) -> None:
    data = _load()
    pins = dict(data.get("pinned_sessions") or {})
    pins.pop((phone or "").strip(), None)
    data["pinned_sessions"] = pins
    _save(data)
