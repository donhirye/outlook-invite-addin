"""Assemble the Releases dashboard view model (cached, refreshable).

Rules:
- Prefer live Cloud Run traffic/revision/image (read-only).
- Commit SHA from Cloud Run GIT_SHA/label, else matching release record.
- Never guess from branch names alone.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.config import (
    CLOUD_RUN_REGION,
    PRODUCTION_BASE_URL,
    PRODUCTION_CLOUD_RUN_PROJECT,
    PRODUCTION_CLOUD_RUN_SERVICE,
    STAGING_BASE_URL,
    STAGING_CLOUD_RUN_PROJECT,
    STAGING_CLOUD_RUN_SERVICE,
)
from app.releases.cloudrun import describe_serving
from app.releases.evals import find_reports_for_sha, latest_summary_unscoped
from app.releases.git_info import collect_git_snapshot, is_ancestor
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
    """yes | no | pending — is tip contained in env commit?"""
    if not tip_sha or not env_sha:
        return "pending"
    contained = is_ancestor(tip_sha, env_sha)
    if contained is True:
        return "yes"
    if contained is False:
        return "no"
    return "pending"


def _status_label(code: str) -> str:
    return {"yes": "Yes", "no": "No", "pending": "—"}.get(code, "—")


def _resolve_environment(
    *,
    name: str,
    record: dict[str, Any],
    live: dict[str, Any],
    cloudrun: dict[str, Any],
) -> dict[str, Any]:
    """Build env card from Cloud Run (preferred), then health + release record."""
    checked_at = _utc_now_iso()
    rec_sha = _real_sha(record.get("git_sha") if record.get("available") else None)
    rec_revision = (record.get("revision") or "").strip() or None
    rec_image = (record.get("image") or "").strip() or None
    health_sha = _real_sha(live.get("git_sha") if live.get("available") else None)
    if health_sha and health_sha.lower() == "unknown":
        health_sha = None

    cr_ok = bool(cloudrun.get("available"))
    cr_revision = (cloudrun.get("revision") or "").strip() or None
    cr_image = (cloudrun.get("image") or "").strip() or None
    cr_sha = _real_sha(cloudrun.get("git_sha"))
    cr_split = bool(cloudrun.get("split"))
    cr_traffic = cloudrun.get("traffic") or []

    serving_revision = cr_revision
    serving_image = cr_image
    serving_sha: str | None = None
    verification = "not_verified"
    verification_label = "Not verified"
    note = ""

    if cr_ok and cr_revision:
        # Live Cloud Run revision is source of truth for what is serving.
        if cr_sha:
            serving_sha = cr_sha
            verification = "verified"
            verification_label = "Verified"
            note = "Live Cloud Run revision (commit from revision env/label)."
        elif rec_sha and rec_revision and rec_revision == cr_revision:
            serving_sha = rec_sha
            verification = "verified"
            verification_label = "Verified"
            note = "Live Cloud Run revision matches the deployment record commit."
        elif rec_sha and rec_image and cr_image and (
            rec_image == cr_image or rec_image.split("@")[-1] == cr_image.split("@")[-1]
        ):
            serving_sha = rec_sha
            verification = "verified"
            verification_label = "Verified"
            note = "Live Cloud Run image matches the deployment record commit."
        elif health_sha:
            serving_sha = health_sha
            verification = "verified"
            verification_label = "Verified"
            note = "Live Cloud Run revision; commit from /health."
        else:
            verification = "verified_revision"
            verification_label = "Verified (revision)"
            note = (
                "Live Cloud Run revision/image confirmed. "
                "Commit id not on the revision — add GIT_SHA on deploy for commit-level tracking."
            )
        if cr_split:
            parts = ", ".join(
                f"{t.get('revision')} ({t.get('percent')}%)"
                for t in cr_traffic
                if (t.get("percent") or 0) > 0
            )
            note += f" Traffic split: {parts}."
    elif health_sha:
        serving_sha = health_sha
        serving_revision = rec_revision
        serving_image = rec_image
        verification = "verified"
        verification_label = "Verified"
        note = "Serving commit from /health (Cloud Run describe unavailable)."
    elif rec_sha:
        verification = "recorded_unverified"
        verification_label = "Record only"
        note = "Deployment record present, but live Cloud Run/health could not confirm it."
    else:
        note = cloudrun.get("detail") or "Could not read live deployment status."

    return {
        "name": name,
        "branch": (record.get("branch") if record.get("available") else None) or None,
        "serving_sha": serving_sha,
        "serving_sha_short": _sha_short(serving_sha),
        "recorded_sha": rec_sha,
        "recorded_sha_short": _sha_short(rec_sha),
        "live_sha": health_sha,
        "live_sha_short": _sha_short(health_sha),
        "revision": serving_revision or rec_revision,
        "image": serving_image or rec_image,
        "deployed_at": record.get("deployed_at") if record.get("available") else None,
        "url": (record.get("url") if record.get("available") else None)
        or (live.get("url") if live.get("available") else None),
        "traffic": cr_traffic,
        "traffic_split": cr_split,
        "verification": verification,
        "verification_label": verification_label,
        "verified": verification in {"verified", "verified_revision"},
        "note": note,
        "checked_at": checked_at,
        "live": live,
        "recorded": record,
        "cloudrun": cloudrun,
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
    staging_cr = describe_serving(
        project=STAGING_CLOUD_RUN_PROJECT,
        region=CLOUD_RUN_REGION,
        service=STAGING_CLOUD_RUN_SERVICE,
    )
    production_cr = describe_serving(
        project=PRODUCTION_CLOUD_RUN_PROJECT,
        region=CLOUD_RUN_REGION,
        service=PRODUCTION_CLOUD_RUN_SERVICE,
    )

    staging = _resolve_environment(
        name="STAGING", record=staging_rec, live=staging_live, cloudrun=staging_cr
    )
    production = _resolve_environment(
        name="PRODUCTION", record=prod_rec, live=prod_live, cloudrun=production_cr
    )

    # Use serving commit when verified; for revision-only verified still allow
    # Yes/No when we have a SHA from the matching record path above.
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
                "decision_date": exp.get("decision_date") or "—",
                "reason": exp.get("reason") or exp.get("notes") or "",
                "commit_id": tip,
                "commit_id_short": _sha_short(tip),
                "in_staging": in_staging,
                "in_staging_label": _status_label(in_staging),
                "in_main": in_main,
                "in_main_label": _status_label(in_main),
                "in_production": in_prod,
                "in_production_label": _status_label(in_prod),
                "evals": evals,
                "eval_summary": exp.get("eval_summary"),
                "pr_url": exp.get("pr_url"),
                "waiting_for_production": (
                    exp["decision"] == "accepted"
                    and in_main == "yes"
                    and in_prod in {"no", "pending"}
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
                "staging_unknown": sum(1 for r in rows if r["in_staging"] == "pending"),
                "base_unknown": sum(1 for r in rows if r["in_production"] == "pending"),
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
