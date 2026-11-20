"""Associate eval report files with a deployed git SHA when metadata allows."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

REPORTS_DIR = BASE_DIR / "evals" / "reports"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _normalize_sha(value: Any) -> str | None:
    if not value or not isinstance(value, str):
        return None
    v = value.strip().lower()
    return v or None


def find_reports_for_sha(git_sha: str | None, *, limit: int = 5) -> list[dict[str, Any]]:
    if not git_sha:
        return []
    want = _normalize_sha(git_sha)
    if not want:
        return []
    short = want[:7]
    if not REPORTS_DIR.is_dir():
        return []

    matches: list[dict[str, Any]] = []
    candidates = sorted(
        list(REPORTS_DIR.glob("staging_*.json"))
        + list(REPORTS_DIR.glob("*_summary.json"))
        + ([REPORTS_DIR / "latest_summary.json"] if (REPORTS_DIR / "latest_summary.json").exists() else []),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    seen: set[str] = set()
    for path in candidates:
        if not path.is_file() or path.name in seen:
            continue
        seen.add(path.name)
        data = _load_json(path)
        if not data:
            continue
        report_sha = _normalize_sha(
            data.get("git_sha") or data.get("commit") or (data.get("meta") or {}).get("git_sha")
        )
        if not report_sha:
            continue
        if report_sha != want and not report_sha.startswith(short) and not want.startswith(report_sha[:7]):
            continue
        matches.append(
            {
                "file": path.name,
                "git_sha": report_sha,
                "passed": data.get("passed"),
                "failed": data.get("failed"),
                "cases_run": data.get("cases_run"),
                "engine": data.get("engine") or data.get("engine_id"),
                "stamp": data.get("stamp") or data.get("generated_at"),
            }
        )
        if len(matches) >= limit:
            break
    return matches


def latest_summary_unscoped() -> dict[str, Any] | None:
    """Return latest_summary.json without claiming it matches a deploy SHA."""
    path = REPORTS_DIR / "latest_summary.json"
    data = _load_json(path)
    if not data:
        return None
    return {
        "file": path.name,
        "git_sha": _normalize_sha(data.get("git_sha") or data.get("commit")),
        "passed": data.get("passed"),
        "failed": data.get("failed"),
        "cases_run": data.get("cases_run"),
        "matched_to_deploy": False,
        "note": "Present on disk; not verified against a deployed commit unless git_sha matches",
    }
