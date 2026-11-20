"""Read-only GitHub metadata for the Releases dashboard (Cloud Run safe).

Uses a fine-grained PAT or GitHub token with contents/metadata/pull-requests read.
Never writes to GitHub. Returns empty/partial data on failure (callers show Unknown).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_TIMEOUT = 20


def _request(url: str, token: str = "") -> Any | None:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "whatsapp-faq-bot-releases",
    }
    if (token or "").strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    req = urllib.request.Request(
        url,
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("GitHub API failed for %s: %s", url, exc)
        return None


def fetch_repo_snapshot(owner: str, repo: str, token: str) -> dict[str, Any]:
    """Return main SHA, feature-like branches, and open/closed PRs by head."""
    base = f"https://api.github.com/repos/{owner}/{repo}"
    out: dict[str, Any] = {
        "available": False,
        "main_sha": None,
        "branches": [],
        "prs_by_head": {},
        "error": None,
    }
    if not owner or not repo:
        out["error"] = "GitHub repo not configured"
        return out
    # token may be empty for public repositories.

    main = _request(f"{base}/commits/main", token)
    if isinstance(main, dict) and main.get("sha"):
        out["main_sha"] = main["sha"]
        commit = main.get("commit") or {}
        out["main_date"] = (commit.get("committer") or {}).get("date")
        out["main_subject"] = (commit.get("message") or "").split("\n", 1)[0]
    else:
        out["error"] = "Could not read main from GitHub"
        return out

    branches_raw = _request(f"{base}/branches?per_page=100", token)
    if not isinstance(branches_raw, list):
        out["error"] = "Could not list branches"
        return out

    feature_branches = []
    for b in branches_raw:
        name = (b.get("name") or "").strip()
        if name in {"main", "master"}:
            continue
        if not (
            name.startswith("feature/")
            or name.startswith("experiment/")
            or name.startswith("cursor/")
            or name.startswith("hotfix/")
        ):
            continue
        commit = b.get("commit") or {}
        tip = commit.get("sha")
        detail = _request(f"{base}/commits/{tip}", token) if tip else None
        tip_date = tip_subject = None
        if isinstance(detail, dict):
            c = detail.get("commit") or {}
            tip_date = (c.get("committer") or {}).get("date")
            tip_subject = (c.get("message") or "").split("\n", 1)[0]
        ahead = behind = None
        cmp = _request(
            f"{base}/compare/main...{urllib.parse.quote(name, safe='')}",
            token,
        )
        if isinstance(cmp, dict):
            ahead = cmp.get("ahead_by")
            behind = cmp.get("behind_by")
        merged = None
        if tip and out["main_sha"]:
            # Compare tip...main: if ahead_by of tip vs main is 0 when comparing?
            # Simpler: if behind_by==0 and ahead_by==0 identical; if tip is ancestor,
            # compare main...tip has ahead_by 0.
            if isinstance(cmp, dict) and cmp.get("ahead_by") == 0:
                merged = True
            elif isinstance(cmp, dict) and (cmp.get("ahead_by") or 0) > 0:
                merged = False
        feature_branches.append(
            {
                "name": name,
                "tip_sha": tip,
                "tip_date": tip_date,
                "tip_subject": tip_subject,
                "ahead": ahead,
                "behind": behind,
                "merged_into_main": merged,
            }
        )

    prs = _request(f"{base}/pulls?state=all&per_page=50", token)
    prs_by_head: dict[str, dict] = {}
    if isinstance(prs, list):
        for pr in prs:
            head = ((pr.get("head") or {}).get("ref") or "").strip()
            if head and head not in prs_by_head:
                prs_by_head[head] = {
                    "number": pr.get("number"),
                    "url": pr.get("html_url"),
                    "state": pr.get("state"),
                    "title": pr.get("title"),
                }

    out["available"] = True
    out["branches"] = feature_branches
    out["prs_by_head"] = prs_by_head
    out["error"] = None
    return out


def compare_contains(owner: str, repo: str, token: str, tip: str, env_sha: str) -> bool | None:
    """True if tip is an ancestor of env_sha (tip contained in env)."""
    if not tip or not env_sha:
        return None
    # compare tip...env: if ahead_by of tip relative to env is 0, tip is behind/equal env
    data = _request(
        f"https://api.github.com/repos/{owner}/{repo}/compare/"
        f"{urllib.parse.quote(tip, safe='')}...{urllib.parse.quote(env_sha, safe='')}",
        token,
    )
    if not isinstance(data, dict):
        return None
    # status: identical | ahead | behind | diverged
    status = data.get("status")
    if status in {"identical", "behind"}:
        # env is ahead or equal => tip is ancestor of env (or same)
        return True
    if status == "ahead":
        return False
    if status == "diverged":
        return False
    return None
