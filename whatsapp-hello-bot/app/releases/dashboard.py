"""Assemble the Releases dashboard view model (cached, refreshable)."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.config import PRODUCTION_BASE_URL, STAGING_BASE_URL
from app.releases.evals import find_reports_for_sha, latest_summary_unscoped
from app.releases.git_info import BranchInfo, GitSnapshot, collect_git_snapshot, commits_between, is_ancestor
from app.releases.live import probe_health
from app.releases.records import load_production_record, load_staging_record
from app.releases.registry import experiments_by_branch, load_experiments

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


def _env_presence(tip_sha: str | None, deployed_sha: str | None) -> str:
    """Return matrix cell: implemented | deployed | experimental | not_present | unknown."""
    if not tip_sha:
        return "unknown"
    if not deployed_sha or deployed_sha in {"Unknown", "Not Verified"}:
        return "unknown"
    # Tip contained in deployed commit => feature is on that environment
    contained = is_ancestor(tip_sha, deployed_sha)
    if contained is True:
        return "deployed"
    if contained is False:
        return "not_present"
    return "unknown"


def _dev_presence(branch: BranchInfo | None, current_branch: str | None) -> str:
    if not branch:
        return "not_present"
    if branch.merged_into_main is True:
        return "implemented"
    if current_branch and branch.name == current_branch:
        return "experimental"
    if (branch.ahead or 0) > 0 or branch.tip_sha:
        return "experimental"
    return "unknown"


def _mermaid(git: GitSnapshot, staging_sha: str | None, prod_sha: str | None) -> str:
    lines = ["flowchart LR", "  main[main]"]
    st_short = _sha_short(staging_sha)
    pr_short = _sha_short(prod_sha)
    if pr_short:
        lines.append(f"  prodMarker[\"PROD {pr_short}\"]")
        lines.append("  main --- prodMarker")
    if st_short:
        lines.append(f"  stgMarker[\"STAGING {st_short}\"]")
        lines.append("  main --- stgMarker")
    for b in git.branches[:12]:
        safe = "".join(ch if ch.isalnum() else "_" for ch in b.name)[:40]
        label = b.name.replace('"', "'")
        tip = _sha_short(b.tip_sha) or "?"
        lines.append(f'  {safe}["{label}\\n{tip}"]')
        lines.append(f"  main --- {safe}")
    if len(git.branches) > 12:
        lines.append(f'  more["+{len(git.branches) - 12} more branches"]')
        lines.append("  main --- more")
    if not git.branches and not st_short and not pr_short:
        lines.append('  empty["No feature branches / deploy markers"]')
        lines.append("  main --- empty")
    return "\n".join(lines)


def _build() -> dict[str, Any]:
    git = collect_git_snapshot()
    registry = experiments_by_branch()
    experiments = load_experiments()

    staging_rec = load_staging_record()
    prod_rec = load_production_record()
    staging_live = probe_health(STAGING_BASE_URL)
    prod_live = probe_health(PRODUCTION_BASE_URL)

    staging_sha = staging_rec.get("git_sha") if staging_rec.get("available") else None
    prod_sha = prod_rec.get("git_sha") if prod_rec.get("available") else None
    # Prefer live SHA when it looks like a real hash
    live_stg = staging_live.get("git_sha")
    if isinstance(live_stg, str) and live_stg not in {"Unknown", "Not Verified"} and len(live_stg) >= 7:
        # keep recorded as recorded; live shown separately — delta uses recorded first, else live
        if not staging_sha:
            staging_sha = live_stg
    live_prod = prod_live.get("git_sha")
    if isinstance(live_prod, str) and live_prod not in {"Unknown", "Not Verified"} and len(live_prod) >= 7:
        if not prod_sha:
            prod_sha = live_prod

    branch_rows: list[dict[str, Any]] = []
    for b in git.branches:
        exp = registry.get(b.name)
        branch_rows.append(
            {
                "name": b.name,
                "is_remote": b.is_remote,
                "tip_sha": b.tip_sha,
                "tip_sha_short": _sha_short(b.tip_sha),
                "tip_date": b.tip_date or "Unknown",
                "tip_subject": b.tip_subject or "Unknown",
                "ahead": b.ahead,
                "behind": b.behind,
                "merged_into_main": b.merged_into_main,
                "first_commit_date": b.first_commit_date or "Unknown",
                "pr_url": b.pr_url or (exp or {}).get("pr_url"),
                "pr_number": b.pr_number,
                "pr_state": b.pr_state or "Unknown",
                "experiment_name": (exp or {}).get("name") or "Unregistered experiment",
                "experiment_objective": (exp or {}).get("objective") or "Unknown",
                "experiment_status": (exp or {}).get("status") or "experimental",
                "registered": bool(exp),
            }
        )

    # Matrix rows: registry first, then unregistered open branches
    seen_branches = {e["branch"] for e in experiments}
    matrix: list[dict[str, Any]] = []
    branch_by_name = {b.name: b for b in git.branches}

    def add_matrix_row(name: str, objective: str, branch_name: str, status: str) -> None:
        b = branch_by_name.get(branch_name)
        tip = b.tip_sha if b else None
        matrix.append(
            {
                "name": name,
                "objective": objective,
                "branch": branch_name,
                "registry_status": status,
                "dev": _dev_presence(b, git.branch),
                "staging": _env_presence(tip, staging_sha),
                "production": _env_presence(tip, prod_sha),
            }
        )

    for exp in experiments:
        add_matrix_row(exp["name"], exp["objective"], exp["branch"], exp["status"])
    for b in git.branches:
        if b.name in seen_branches:
            continue
        add_matrix_row(
            "Unregistered experiment",
            "Unknown — add to data/experiments.json",
            b.name,
            "experimental",
        )

    delta: list[str] = []
    if staging_sha and prod_sha:
        delta = commits_between(prod_sha, staging_sha)
    elif staging_sha or prod_sha:
        delta = []  # incomplete — UI shows Not Verified for missing side

    staging_tests = find_reports_for_sha(staging_sha)
    if not staging_tests:
        staging_tests_note = latest_summary_unscoped()
    else:
        staging_tests_note = None

    return {
        "refreshed_at": _utc_now_iso(),
        "dev": {
            "available": git.available,
            "error": git.error,
            "branch": git.branch or "Unknown",
            "commit": git.commit or "Unknown",
            "short_commit": git.short_commit or "Unknown",
            "commit_subject": git.commit_subject or "Unknown",
            "commit_date": git.commit_date or "Unknown",
            "dirty_files": git.dirty_files,
            "main_sha": git.main_sha,
            "branches": branch_rows,
        },
        "staging": {
            "recorded": staging_rec,
            "live": staging_live,
            "tests": staging_tests,
            "tests_unscoped": staging_tests_note,
            "delta_vs_prod": delta,
            "delta_status": (
                "Recorded"
                if staging_sha and prod_sha
                else "Not Verified"
            ),
        },
        "production": {
            "recorded": prod_rec,
            "live": prod_live,
        },
        "matrix": matrix,
        "mermaid": _mermaid(git, staging_sha, prod_sha),
        "config": {
            "staging_base_url": STAGING_BASE_URL or None,
            "production_base_url": PRODUCTION_BASE_URL or None,
        },
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
