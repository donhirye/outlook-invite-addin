"""Lightweight experiment registry (committed JSON)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import SHARED_DATA_DIR

logger = logging.getLogger(__name__)

REGISTRY_PATH = SHARED_DATA_DIR / "experiments.json"
VALID_STATUSES = frozenset({"experimental", "ready", "shipped", "abandoned"})


def load_experiments() -> list[dict[str, Any]]:
    path = REGISTRY_PATH
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read experiments registry: %s", exc)
        return []
    if not isinstance(raw, dict):
        return []
    items = raw.get("experiments")
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        branch = (item.get("branch") or "").strip()
        name = (item.get("name") or "").strip()
        if not branch or not name:
            continue
        status = (item.get("status") or "experimental").strip().lower()
        if status not in VALID_STATUSES:
            status = "experimental"
        out.append(
            {
                "id": (item.get("id") or branch).strip(),
                "name": name,
                "objective": (item.get("objective") or "").strip() or "Unknown",
                "branch": branch,
                "status": status,
                "pr_url": (item.get("pr_url") or "").strip() or None,
                "notes": (item.get("notes") or "").strip() or None,
            }
        )
    return out


def experiments_by_branch() -> dict[str, dict[str, Any]]:
    return {e["branch"]: e for e in load_experiments()}


def ensure_registry_example(path: Path | None = None) -> None:
    """Create an empty registry file if missing (dev convenience; tests may call)."""
    target = path or REGISTRY_PATH
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"experiments": []}, indent=2) + "\n",
        encoding="utf-8",
    )
