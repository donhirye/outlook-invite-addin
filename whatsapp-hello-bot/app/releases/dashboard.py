"""Assemble the Releases dashboard view model (cached, refreshable).

Rules:
- Never guess staging/production commits from branch names.
- Yes / No / Unknown only from verified SHAs.
- Production: health + release records; live-verified only when health git_sha
  agrees with the record (or health alone provides a git_sha).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.config import PRODUCTION_BASE_URL, STAGING_BASE_URL
from app.releases.evals import find_reports_for_sha, latest_summary_unscoped
from app.releases.git_info import GitSnapshot, collect_git_snapshot, is_ancestor
from app.releases.live import probe_health
from app.releases.records import load_production_record, load_staging_record
from app.releases.registry import experiments_by_branch, load_experiments, load_registry_document

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cache_at: float | None = None
_CACHE_TTL_SEC = 60


def clear_cache() -> None:
    global _cache, _cache_at
    with _lock:
        _cache = None
        _cache_at = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha_short(sha: str | None) -> str | None:
    if not sha or sha in {"Unknown", "Not Verified"}:
        return None
    return sha[:7]


def _real_sha(*candidates: Any) -> str | None:
    for value in candidates:
        if not isinstance(value, str):
            continue
        v = value.strip()
        if len(v) >= 7 and v not in {"Unknown", "Not Verified"}:
            return v
    return None


def _sha_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    a, b = a.lower(), b.lower()
    return a.startswith(b[:7]) or b.startswith(a[:7]) or a == b


def _contains(tip_sha: str | None, env_sha: str | None) -> str:
    """yes | no | unknown — is tip contained in env commit?"""
    if not tip_sha or not env_sha:
        return "unknown"
    contained = is_ancestor(tip_sha, env_sha)
    if contained is True:
        return "yes"
    if contained is False:
        return "no"
    return "unknown"


def _resolve_environment(
    *,
    name: str,
    record: dict[str, Any],
    live: dict[str, Any],
) -> dict[str, Any]:
    """Build a simple env card. Never invent a serving commit."""
    checked_at = _utc_now_iso()
    rec_sha = _real_sha(record.get("git_sha") if record.get("available") else None)
    live_sha = _real_sha(live.get("git_sha") if live.get("available") else None)
    # Treat literal "Unknown" from probe as missing.
    if live_sha and live_sha.lower() == "unknown":
        live_sha = None

    serving_sha: str | None = None
    verification = "not_verified"
    verification_label = "Not verified"
    note = ""

    if live_sha and rec_sha and _sha_match(live_sha, rec_sha):
        serving_sha = rec_sha if len(rec_sha) >= len(live_sha) else live_sha
        verification = "verified"
        verification_label = "Verified"
        note = "Live /health git_sha matches the deployment record."
    elif live_sha and not rec_sha:
        serving_sha = live_sha
        verification = "verified_health_only"
        verification_label = "Verified (health only)"
        note = "Serving commit from /health. No deployment record available for revision/image."
    elif rec_sha and not live_sha:
        serving_sha = None  # do not treat record as live-verified serving commit
        verification = "recorded_unverified"
        verification_label = "Recorded — not live-verified"
        note = (
            "A deployment record exists, but live /health did not return a matching git_sha, "
            "so this cannot be confirmed as the currently serving revision."
        )
    elif live_sha and rec_sha and not _sha_match(live_sha, rec_sha):
        serving_sha = None
        verification = "conflict"
        verification_label = "Not verified (mismatch)"
        note = (
            f"Live health commit ({_sha_short(live_sha)}) does not match "
            f"deployment record ({_sha_short(rec_sha)})."
        )
    else:
        note = "No live health git_sha and no deployment record."

    return {
        "name": name,
        "branch": (record.get("branch") if record.get("available") else None) or None,
        "serving_sha": serving_sha,
        "serving_sha_short": _sha_short(serving_sha),
        "recorded_sha": rec_sha,
        "recorded_sha_short": _sha_short(rec_sha),
        "live_sha": live_sha,
        "live_sha_short": _sha_short(live_sha),
        "revision": record.get("revision") if record.get("available") else None,
        "image": record.get("image") if record.get("available") else None,
        "deployed_at": record.get("deployed_at") if record.get("available") else None,
        "url": (record.get("url") if record.get("available") else None)
        or (live.get("url") if live.get("available") else None),
        "verification": verification,
        "verification_label": verification_label,
        "verified": verification in {"verified", "verified_health_only"},
        "note": note,
        "checked_at": checked_at,
        "live": live,
        "recorded": record,
    }


def _build() -> dict[str, Any]:
    git = collect_git_snapshot()
    registry_doc = load_registry_document()
    experiments = load_experiments()
    registry = experiments_by_branch()

    staging_rec = load_staging_record()
    prod_rec = load_production_record()
    staging_live = probe_health(STAGING_BASE_URL)
    prod_live = probe_health(PRODUCTION_BASE_URL)

    staging = _resolve_environment(name="STAGING", record=staging_rec, live=staging_live)
    production = _resolve_environment(name="PRODUCTION", record=prod_rec, live=prod_live)

    staging_sha = staging["serving_sha"] if staging["verified"] else None
    prod_sha = production["serving_sha"] if production["verified"] else None
    main_sha = git.main_sha if git.available else None

    tip_by_branch = {b.name: b for b in git.branches}

    rows: list[dict[str, Any]] = []
    testing_count = 0
    for exp in experiments:
        branch = exp["branch"]
        b = tip_by_branch.get(branch)
        tip = _real_sha(exp.get("commit_id"), b.tip_sha if b else None)
        in_staging = _contains(tip, staging_sha)
        in_main = _contains(tip, main_sha)
        in_prod = _contains(tip, prod_sha)
        if exp["decision"] == "testing":
            testing_count += 1
        evals = find_reports_for_sha(tip) if tip else []
        rows.append(
            {
                "id": exp["id"],
                "name": exp["name"],
                "objective": exp["objective"],
                "branch": branch,
                "decision": exp["decision"],
                "decision_label": exp["decision_label"],
                "decision_date": exp.get("decision_date") or "Unknown",
                "reason": exp.get("reason") or exp.get("notes") or "",
                "commit_id": tip,
                "commit_id_short": _sha_short(tip),
                "in_staging": in_staging,
                "in_main": in_main,
                "in_production": in_prod,
                "evals": evals,
                "eval_summary": exp.get("eval_summary"),
                "pr_url": exp.get("pr_url"),
                "waiting_for_production": (
                    exp["decision"] == "accepted"
                    and in_main == "yes"
                    and in_prod in {"no", "unknown"}
                ),
            }
        )

    waiting = [r for r in rows if r["waiting_for_production"]]

    # Technical details (collapsed in UI)
    tech = {
        "git_available": git.available,
        "git_source": getattr(git, "source", None),
        "git_error": git.error,
        "main_sha": main_sha,
        "main_sha_short": _sha_short(main_sha),
        "branches": [
            {
                "name": b.name,
                "tip_sha_short": _sha_short(b.tip_sha),
                "ahead": b.ahead,
                "behind": b.behind,
                "merged_into_main": b.merged_into_main,
            }
            for b in git.branches
        ],
        "registry_source": registry_doc.get("source"),
        "registry_path": registry_doc.get("path"),
        "history": (registry_doc.get("history") or [])[-20:],
        "staging_tests_unscoped": latest_summary_unscoped(),
        "config": {
            "staging_base_url": STAGING_BASE_URL or None,
            "production_base_url": PRODUCTION_BASE_URL or None,
        },
    }

    return {
        "refreshed_at": _utc_now_iso(),
        "staging": staging,
        "production": production,
        "experiments": rows,
        "waiting_for_production": waiting,
        "testing_count": testing_count,
        "multiple_testing": testing_count > 1,
        "legend": {
            "feature": "What you are trying (name + Git branch).",
            "decision": "Your choice: Testing, Accepted, Parked, or Rejected.",
            "in_staging": "Is this feature’s commit inside the currently verified staging deploy?",
            "in_main": "Is this feature’s commit already in the main branch on GitHub?",
            "in_production": "Is this feature’s commit inside the currently verified production deploy?",
        },
        "tech": tech,
        # Backward-compatible aliases used by older tests (minimal).
        "base": {
            "sha": prod_sha,
            "sha_short": _sha_short(prod_sha),
            "source": "production" if prod_sha else "unknown",
            "note": production["note"],
        },
        "formula": {
            "base_source": "production" if prod_sha else "unknown",
            "base_sha": prod_sha,
            "base_sha_short": _sha_short(prod_sha),
            "base_note": production["note"],
            "staging_source": "staging_deploy" if staging_sha else "unknown",
            "staging_sha": staging_sha,
            "staging_sha_short": _sha_short(staging_sha),
            "staging_note": staging["note"],
            "staging_expression": "Verified" if staging_sha else "Not Verified",
            "dev_expression": "retired",
            "funnel": {
                "tracked": len(rows),
                "on_dev": 0,
                "on_staging": sum(1 for r in rows if r["in_staging"] == "yes"),
                "in_base": sum(1 for r in rows if r["in_production"] == "yes"),
                "staging_unknown": sum(1 for r in rows if r["in_staging"] == "unknown"),
                "base_unknown": sum(1 for r in rows if r["in_production"] == "unknown"),
                "dev_only": 0,
                "dev_pending": 0,
                "staging_candidates": sum(
                    1 for r in rows if r["in_staging"] == "yes" and r["in_production"] != "yes"
                ),
            },
        },
        "dev": {
            "available": git.available,
            "error": git.error,
            "branch": git.branch or "Unknown",
            "commit": git.commit or "Unknown",
            "short_commit": git.short_commit or "Unknown",
            "branches": tech["branches"],
        },
        "matrix": [
            {
                "name": r["name"],
                "objective": r["objective"],
                "branch": r["branch"],
                "on_dev": "yes" if tip_by_branch.get(r["branch"]) else "no",
                "on_staging": r["in_staging"],
                "on_prod": r["in_production"],
                "lane": r["decision"],
                "tip_sha_short": r["commit_id_short"],
                "registered": True,
            }
            for r in rows
        ],
        "mermaid": "",
    }


def get_dashboard(*, force: bool = False) -> dict[str, Any]:
    global _cache, _cache_at
    with _lock:
        now = time.monotonic()
        if (
            not force
            and _cache is not None
            and _cache_at is not None
            and (now - _cache_at) < _CACHE_TTL_SEC
        ):
            return _cache
        data = _build()
        _cache = data
        _cache_at = now
        return data
