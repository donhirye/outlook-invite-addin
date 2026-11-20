"""Experiment decision registry.

On staging Cloud Run, decisions are stored in the staging GCS bucket
(gs://…/releases/experiments/decisions.json) with an append-only history.
Local DEV falls back to the committed data/experiments.json seed file.
Never writes to Git or Cloud Run deploy APIs.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import FAQ_GCS_BUCKET, SHARED_DATA_DIR

logger = logging.getLogger(__name__)

REGISTRY_PATH = SHARED_DATA_DIR / "experiments.json"
GCS_DECISIONS_OBJECT = "releases/experiments/decisions.json"

# User-facing decisions (dashboard).
DECISIONS = frozenset({"testing", "accepted", "parked", "rejected"})
DECISION_LABELS = {
    "testing": "Testing",
    "accepted": "Accepted",
    "parked": "Parked",
    "rejected": "Rejected",
}
# Migrate older registry statuses.
_LEGACY = {
    "experimental": "testing",
    "ready": "accepted",
    "shipped": "accepted",
    "abandoned": "rejected",
}

_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gcs_enabled() -> bool:
    return bool(FAQ_GCS_BUCKET)


def _read_gcs() -> dict[str, Any] | None:
    if not _gcs_enabled():
        return None
    try:
        from google.cloud import storage  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.debug("GCS unavailable for decisions: %s", exc)
        return None
    try:
        blob = storage.Client().bucket(FAQ_GCS_BUCKET).blob(GCS_DECISIONS_OBJECT)
        if not blob.exists():
            return None
        data = json.loads(blob.download_as_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read GCS decisions: %s", exc)
        return None


def _write_gcs(doc: dict[str, Any]) -> None:
    if not _gcs_enabled():
        raise RuntimeError("FAQ_GCS_BUCKET is not set; cannot save decisions on this host")
    from google.cloud import storage  # type: ignore

    blob = storage.Client().bucket(FAQ_GCS_BUCKET).blob(GCS_DECISIONS_OBJECT)
    blob.upload_from_string(
        json.dumps(doc, indent=2) + "\n",
        content_type="application/json",
    )


def _read_local(path: Path | None = None) -> dict[str, Any]:
    target = path or REGISTRY_PATH
    if not target.exists():
        return {"experiments": [], "history": []}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read experiments registry: %s", exc)
        return {"experiments": [], "history": []}
    if not isinstance(raw, dict):
        return {"experiments": [], "history": []}
    return raw


def _normalize_decision(value: str | None) -> str:
    raw = (value or "testing").strip().lower()
    if raw in DECISIONS:
        return raw
    return _LEGACY.get(raw, "testing")


def _normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    branch = (item.get("branch") or "").strip()
    name = (item.get("name") or "").strip()
    if not branch or not name:
        return None
    decision = _normalize_decision(item.get("decision") or item.get("status"))
    return {
        "id": (item.get("id") or branch).strip(),
        "name": name,
        "objective": (item.get("objective") or "").strip() or "Unknown",
        "branch": branch,
        "decision": decision,
        "decision_label": DECISION_LABELS[decision],
        # Keep legacy key for older callers/tests.
        "status": decision,
        "decision_date": (item.get("decision_date") or "").strip() or None,
        "reason": (item.get("reason") or item.get("notes") or "").strip() or None,
        "notes": (item.get("notes") or item.get("reason") or "").strip() or None,
        "commit_id": (item.get("commit_id") or item.get("tip_sha") or "").strip() or None,
        "pr_url": (item.get("pr_url") or "").strip() or None,
        "eval_summary": (item.get("eval_summary") or "").strip() or None,
    }


def load_registry_document() -> dict[str, Any]:
    """Prefer durable GCS decisions on staging; else local seed file."""
    gcs = _read_gcs()
    if gcs is not None:
        return {
            "experiments": gcs.get("experiments") if isinstance(gcs.get("experiments"), list) else [],
            "history": gcs.get("history") if isinstance(gcs.get("history"), list) else [],
            "source": "gcs",
            "path": f"gs://{FAQ_GCS_BUCKET}/{GCS_DECISIONS_OBJECT}",
        }
    local = _read_local()
    return {
        "experiments": local.get("experiments") if isinstance(local.get("experiments"), list) else [],
        "history": local.get("history") if isinstance(local.get("history"), list) else [],
        "source": "local",
        "path": str(REGISTRY_PATH),
    }


def load_experiments() -> list[dict[str, Any]]:
    doc = load_registry_document()
    out: list[dict[str, Any]] = []
    for item in doc["experiments"]:
        norm = _normalize_item(item if isinstance(item, dict) else {})
        if norm:
            out.append(norm)
    return out


def experiments_by_branch() -> dict[str, dict[str, Any]]:
    return {e["branch"]: e for e in load_experiments()}


def record_decision(
    *,
    experiment_id: str,
    decision: str,
    reason: str = "",
    commit_id: str = "",
    actor: str = "admin",
) -> dict[str, Any]:
    """Update one experiment decision and append history. GCS on staging; local file in DEV."""
    decision = _normalize_decision(decision)
    if decision not in DECISIONS:
        raise ValueError(f"Invalid decision: {decision}")

    with _lock:
        # Seed from GCS or local, then write back to the durable target.
        doc = load_registry_document()
        experiments = [
            dict(x) for x in doc["experiments"] if isinstance(x, dict)
        ]
        history = [dict(x) for x in doc["history"] if isinstance(x, dict)]

        target = None
        for item in experiments:
            eid = (item.get("id") or item.get("branch") or "").strip()
            if eid == experiment_id or (item.get("branch") or "").strip() == experiment_id:
                target = item
                break
        if target is None:
            raise KeyError(f"Unknown experiment: {experiment_id}")

        before = _normalize_decision(target.get("decision") or target.get("status"))
        now = _utc_now()
        target["decision"] = decision
        target["status"] = decision  # legacy mirror
        target["decision_date"] = now
        if reason.strip():
            target["reason"] = reason.strip()
            target["notes"] = reason.strip()
        if commit_id.strip():
            target["commit_id"] = commit_id.strip()

        history.append(
            {
                "at": now,
                "actor": actor,
                "experiment_id": (target.get("id") or experiment_id),
                "branch": target.get("branch"),
                "from": before,
                "to": decision,
                "reason": reason.strip() or None,
                "commit_id": commit_id.strip() or None,
            }
        )
        out_doc = {
            "updated_at": now,
            "experiments": experiments,
            "history": history[-200:],  # keep recent audit entries
        }

        if _gcs_enabled():
            _write_gcs(out_doc)
            source = "gcs"
        else:
            REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            REGISTRY_PATH.write_text(json.dumps(out_doc, indent=2) + "\n", encoding="utf-8")
            source = "local"

        return {
            "ok": True,
            "source": source,
            "experiment": _normalize_item(target),
        }


def ensure_registry_example(path: Path | None = None) -> None:
    """Create an empty registry file if missing (dev convenience; tests may call)."""
    target = path or REGISTRY_PATH
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"experiments": [], "history": []}, indent=2) + "\n",
        encoding="utf-8",
    )
