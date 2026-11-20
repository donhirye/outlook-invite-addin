"""Assemble the Releases dashboard view model (cached, refreshable)."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.config import PRODUCTION_BASE_URL, STAGING_BASE_URL
from app.releases.evals import find_reports_for_sha, latest_summary_unscoped
from app.releases.git_info import (
    BranchInfo,
    GitSnapshot,
    collect_git_snapshot,
    commits_between,
    is_ancestor,
    resolve_ref_sha,
)

# Branch tip used as staging proxy when no deploy record / live GIT_SHA exists.
_STAGING_BRANCH_REFS = (
    "origin/feature/staging-environment",
    "feature/staging-environment",
)
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


def _real_sha(*candidates: Any) -> str | None:
    for value in candidates:
        if not isinstance(value, str):
            continue
        v = value.strip()
        if len(v) >= 7 and v not in {"Unknown", "Not Verified"}:
            return v
    return None


def _contains(tip_sha: str | None, env_sha: str | None) -> str:
    """yes | no | unknown — is tip contained in env commit?"""
    if not tip_sha:
        return "unknown"
    if not env_sha:
        return "unknown"
    contained = is_ancestor(tip_sha, env_sha)
    if contained is True:
        return "yes"
    if contained is False:
        return "no"
    return "unknown"


def _lane(*, on_dev: bool, on_staging: str, on_prod: str) -> str:
    """Promotion lane label for one feature."""
    if on_prod == "yes":
        return "in_base"
    if on_staging == "yes" and on_prod == "no":
        return "staging_candidate"
    if on_staging == "yes" and on_prod == "unknown":
        return "on_staging"
    if on_dev and on_staging == "no" and on_prod == "no":
        return "dev_only"
    if on_dev and (on_staging == "unknown" or on_prod == "unknown"):
        return "dev_pending"
    if not on_dev and on_prod == "no" and on_staging == "no":
        return "not_present"
    return "unknown"


def _mermaid(
    git: GitSnapshot,
    *,
    base_sha: str | None,
    staging_sha: str | None,
    formula: dict[str, Any],
) -> str:
    lines = ["flowchart LR"]
    base_label = _sha_short(base_sha) or "?"
    lines.append(f'  PROD["PROD\\n{base_label}"]')
    st_extras = formula.get("staging_extras") or []
    dev_extras = formula.get("dev_extras") or []
    if staging_sha:
        st_bits = ", ".join(st_extras[:5]) if st_extras else "(no extras)"
        if len(st_extras) > 5:
            st_bits += f", +{len(st_extras) - 5}"
        lines.append(f'  STG["STAGING = PROD +\\n{st_bits}"]')
        lines.append("  PROD --> STG")
    else:
        lines.append('  STG["STAGING\\nNot Verified"]')
        lines.append("  PROD -.-> STG")
    if dev_extras:
        dev_bits = ", ".join(dev_extras[:5])
        if len(dev_extras) > 5:
            dev_bits += f", +{len(dev_extras) - 5}"
        lines.append(f'  DEV["DEV = PROD +\\n{dev_bits}"]')
    else:
        lines.append('  DEV["DEV = PROD\\n(no extras tracked)"]')
    lines.append("  PROD --> DEV")
    return "\n".join(lines)


def _build_matrix(
    *,
    git: GitSnapshot,
    experiments: list[dict[str, Any]],
    registry: dict[str, dict[str, Any]],
    base_sha: str | None,
    staging_sha: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    branch_by_name = {b.name: b for b in git.branches}
    seen = {e["branch"] for e in experiments}
    rows: list[dict[str, Any]] = []

    def add_row(
        name: str,
        objective: str,
        branch_name: str,
        status: str,
        *,
        registered: bool,
    ) -> None:
        b = branch_by_name.get(branch_name)
        tip = b.tip_sha if b else None
        on_dev = b is not None
        on_staging = _contains(tip, staging_sha)
        on_prod = _contains(tip, base_sha)
        lane = _lane(on_dev=on_dev, on_staging=on_staging, on_prod=on_prod)
        rows.append(
            {
                "name": name,
                "objective": objective,
                "branch": branch_name,
                "registry_status": status,
                "registered": registered,
                "tip_sha_short": _sha_short(tip),
                "on_dev": "yes" if on_dev else "no",
                "on_staging": on_staging,
                "on_prod": on_prod,
                "lane": lane,
            }
        )

    for exp in experiments:
        add_row(
            exp["name"],
            exp["objective"],
            exp["branch"],
            exp["status"],
            registered=True,
        )

    # Unregistered: only tips still outside BASE (active deltas). Hide merged leftovers.
    for b in git.branches:
        if b.name in seen:
            continue
        if not b.tip_sha:
            continue
        in_base = _contains(b.tip_sha, base_sha)
        if in_base == "yes":
            continue
        exp = registry.get(b.name)
        add_row(
            (exp or {}).get("name") or "Unregistered experiment",
            (exp or {}).get("objective") or "Unknown — add to data/experiments.json",
            b.name,
            (exp or {}).get("status") or "experimental",
            registered=False,
        )

    # Funnel counts (features we are tracking in this matrix)
    n = len(rows)
    on_dev_n = sum(1 for r in rows if r["on_dev"] == "yes")
    on_stg_n = sum(1 for r in rows if r["on_staging"] == "yes")
    on_prod_n = sum(1 for r in rows if r["on_prod"] == "yes")
    stg_unknown = sum(1 for r in rows if r["on_staging"] == "unknown")
    prod_unknown = sum(1 for r in rows if r["on_prod"] == "unknown")

    staging_extras = [
        r["name"] if r["registered"] else r["branch"]
        for r in rows
        if r["on_staging"] == "yes" and r["on_prod"] == "no"
    ]
    # Also staging yes + prod unknown counts as staging-side extra pending base verify
    staging_extras += [
        r["name"] if r["registered"] else r["branch"]
        for r in rows
        if r["on_staging"] == "yes" and r["on_prod"] == "unknown"
        and (r["name"] if r["registered"] else r["branch"]) not in staging_extras
    ]
    dev_extras = [
        r["name"] if r["registered"] else r["branch"]
        for r in rows
        if r["on_dev"] == "yes" and r["on_prod"] != "yes"
    ]

    formula = {
        "base_label": "PROD",
        "staging_expression": (
            "PROD + " + " + ".join(staging_extras)
            if staging_extras
            else ("PROD" if staging_sha else "Not Verified")
        ),
        "dev_expression": (
            "PROD + " + " + ".join(dev_extras) if dev_extras else "PROD"
        ),
        "staging_extras": staging_extras,
        "dev_extras": dev_extras,
        "funnel": {
            "tracked": n,
            "on_dev": on_dev_n,
            "on_staging": on_stg_n,
            "in_base": on_prod_n,
            "staging_unknown": stg_unknown,
            "base_unknown": prod_unknown,
            "dev_only": sum(1 for r in rows if r["lane"] == "dev_only"),
            "dev_pending": sum(1 for r in rows if r["lane"] == "dev_pending"),
            "staging_candidates": sum(
                1 for r in rows if r["lane"] in {"staging_candidate", "on_staging"}
            ),
        },
    }
    return rows, formula


def _build() -> dict[str, Any]:
    git = collect_git_snapshot()
    registry = experiments_by_branch()
    experiments = load_experiments()

    staging_rec = load_staging_record()
    prod_rec = load_production_record()
    staging_live = probe_health(STAGING_BASE_URL)
    prod_live = probe_health(PRODUCTION_BASE_URL)

    staging_deploy_sha = _real_sha(
        staging_rec.get("git_sha") if staging_rec.get("available") else None,
        staging_live.get("git_sha"),
    )
    prod_sha = _real_sha(
        prod_rec.get("git_sha") if prod_rec.get("available") else None,
        prod_live.get("git_sha"),
    )

    # BASE = production when known; otherwise origin/main as an honest proxy.
    if prod_sha:
        base_sha = prod_sha
        base_source = "production"
        base_note = "PROD is the production deploy commit."
    elif git.main_sha:
        base_sha = git.main_sha
        base_source = "main_proxy"
        base_note = (
            "PROD is origin/main (proxy). Production deploy SHA is Not Verified — "
            "pull a production release record or set PRODUCTION_BASE_URL after GIT_SHA is live."
        )
    else:
        base_sha = None
        base_source = "unknown"
        base_note = "PROD is Unknown — no production SHA and no main ref."

    # STAGING = deploy/live SHA when known; else tip of feature/staging-environment.
    if staging_deploy_sha:
        staging_sha = staging_deploy_sha
        staging_source = "staging_deploy"
        staging_note = "STAGING is the recorded/live Cloud Run deploy commit."
    else:
        staging_sha = resolve_ref_sha(*_STAGING_BRANCH_REFS)
        if staging_sha:
            staging_source = "staging_branch_proxy"
            staging_note = (
                "STAGING is the tip of feature/staging-environment (proxy). "
                "Redeploy staging to write a deploy record / GIT_SHA for verified status."
            )
        else:
            staging_sha = None
            staging_source = "unknown"
            staging_note = "STAGING is Unknown — no deploy SHA and no staging branch tip."

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

    matrix, formula = _build_matrix(
        git=git,
        experiments=experiments,
        registry=registry,
        base_sha=base_sha,
        staging_sha=staging_sha,
    )
    formula["base_sha"] = base_sha
    formula["base_sha_short"] = _sha_short(base_sha)
    formula["base_source"] = base_source
    formula["base_note"] = base_note
    formula["staging_sha"] = staging_sha
    formula["staging_sha_short"] = _sha_short(staging_sha)
    formula["staging_source"] = staging_source
    formula["staging_note"] = staging_note
    # Prefer a concrete STAGING = PROD + … line once we have any staging SHA.
    if staging_sha and formula.get("staging_expression") == "Not Verified":
        extras = formula.get("staging_extras") or []
        formula["staging_expression"] = (
            "PROD + " + " + ".join(extras) if extras else "PROD"
        )

    delta: list[str] = []
    delta_status = "Not Verified"
    if staging_sha and base_sha:
        delta = commits_between(base_sha, staging_sha)
        delta_status = "Recorded"

    staging_tests = find_reports_for_sha(staging_sha)
    staging_tests_note = None if staging_tests else latest_summary_unscoped()

    return {
        "refreshed_at": _utc_now_iso(),
        "base": {
            "sha": base_sha,
            "sha_short": _sha_short(base_sha),
            "source": base_source,
            "note": base_note,
        },
        "formula": formula,
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
            "delta_status": delta_status,
        },
        "production": {
            "recorded": prod_rec,
            "live": prod_live,
        },
        "matrix": matrix,
        "mermaid": _mermaid(
            git, base_sha=base_sha, staging_sha=staging_sha, formula=formula
        ),
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
