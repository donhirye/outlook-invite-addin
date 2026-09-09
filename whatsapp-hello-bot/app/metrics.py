import json
import logging
from pathlib import Path
from threading import Lock

from app.config import METRICS_FILE

logger = logging.getLogger(__name__)
_lock = Lock()


def _empty_metrics() -> dict:
    return {
        "questions_asked": 0,
        "unique_senders": [],
        "last_e2e_ms": None,
        "last_faq_total_ms": None,
    }


def _load(path: Path) -> dict:
    if not path.exists():
        return _empty_metrics()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to read metrics file; starting fresh")
        return _empty_metrics()
    senders = data.get("unique_senders") or []
    if not isinstance(senders, list):
        senders = []
    return {
        "questions_asked": int(data.get("questions_asked") or 0),
        "unique_senders": [str(s) for s in senders],
        "last_e2e_ms": data.get("last_e2e_ms"),
        "last_faq_total_ms": data.get("last_faq_total_ms"),
    }


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def record_question(
    sender_phone: str,
    *,
    e2e_ms: float | None = None,
    faq_total_ms: float | None = None,
    path: Path | None = None,
) -> dict:
    """Increment question count and track unique sender phones."""
    metrics_path = path or METRICS_FILE
    with _lock:
        data = _load(metrics_path)
        data["questions_asked"] = int(data.get("questions_asked") or 0) + 1
        senders = list(data.get("unique_senders") or [])
        phone = (sender_phone or "").strip()
        if phone and phone not in senders:
            senders.append(phone)
        data["unique_senders"] = senders
        if e2e_ms is not None:
            data["last_e2e_ms"] = round(e2e_ms, 1)
        if faq_total_ms is not None:
            data["last_faq_total_ms"] = round(faq_total_ms, 1)
        _save(metrics_path, data)
        snapshot = {
            "questions_asked": data["questions_asked"],
            "unique_users": len(senders),
            "last_e2e_ms": data.get("last_e2e_ms"),
            "last_faq_total_ms": data.get("last_faq_total_ms"),
        }
    logger.info(
        "usage questions_asked=%s unique_users=%s last_e2e_ms=%s last_faq_total_ms=%s",
        snapshot["questions_asked"],
        snapshot["unique_users"],
        snapshot["last_e2e_ms"],
        snapshot["last_faq_total_ms"],
    )
    return snapshot


def get_metrics(path: Path | None = None) -> dict:
    metrics_path = path or METRICS_FILE
    with _lock:
        data = _load(metrics_path)
        senders = data.get("unique_senders") or []
        return {
            "questions_asked": int(data.get("questions_asked") or 0),
            "unique_users": len(senders),
            "last_e2e_ms": data.get("last_e2e_ms"),
            "last_faq_total_ms": data.get("last_faq_total_ms"),
        }
