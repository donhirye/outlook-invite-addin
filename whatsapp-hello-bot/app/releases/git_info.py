"""Git / GitHub probes for the Releases dashboard. Never raises to callers.

Local DEV uses the laptop git worktree. Staging Cloud Run uses the GitHub API
(read-only token) because there is no .git checkout in the container.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.config import BASE_DIR, GITHUB_REPO, GITHUB_TOKEN

logger = logging.getLogger(__name__)

_GIT_TIMEOUT = 8
_GH_TIMEOUT = 10
_FEATURE_RE = re.compile(
    r"^(feature/|cursor/|experiment/|hotfix/)",
    re.IGNORECASE,
)


def repo_root() -> Path:
    """Monorepo root (parent of whatsapp-hello-bot)."""
    return BASE_DIR.parent


def _run(args: list[str], *, cwd: Path | None = None, timeout: int = _GIT_TIMEOUT) -> str | None:
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd or repo_root()),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("command failed %s: %s", args[:2], exc)
        return None
    if completed.returncode != 0:
        return None
    return (completed.stdout or "").strip()


@dataclass
class BranchInfo:
    name: str
    is_remote: bool = False
    tip_sha: str | None = None
    tip_date: str | None = None
    tip_subject: str | None = None
    ahead: int | None = None
    behind: int | None = None
    merged_into_main: bool | None = None
    first_commit_date: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    pr_state: str | None = None


@dataclass
class GitSnapshot:
    available: bool
    branch: str | None = None
    commit: str | None = None
    short_commit: str | None = None
    commit_subject: str | None = None
    commit_date: str | None = None
    dirty_files: list[str] = field(default_factory=list)
    main_sha: str | None = None
    branches: list[BranchInfo] = field(default_factory=list)
    error: str | None = None
    source: str | None = None  # "local_git" | "github_api"

    def as_dict(self) -> dict:
        return asdict(self)


def _github_owner_repo() -> tuple[str, str] | None:
    raw = (GITHUB_REPO or "").strip().strip("/")
    if "/" not in raw:
        return None
    owner, repo = raw.split("/", 1)
    if not owner or not repo:
        return None
    return owner, repo


def _collect_via_github() -> GitSnapshot | None:
    token = (GITHUB_TOKEN or "").strip()
    owner_repo = _github_owner_repo()
    if not token or not owner_repo:
        return None
    owner, repo = owner_repo
    try:
        from app.releases.github_api import fetch_repo_snapshot
    except Exception as exc:  # noqa: BLE001
        logger.warning("GitHub client import failed: %s", exc)
        return None

    snap = fetch_repo_snapshot(owner, repo, token)
    if not snap.get("available"):
        return GitSnapshot(
            available=False,
            error=snap.get("error") or "GitHub metadata unavailable",
            source="github_api",
        )

    from app.config import DEPLOY_BRANCH, GIT_SHA

    branches: list[BranchInfo] = []
    prs = snap.get("prs_by_head") or {}
    for b in snap.get("branches") or []:
        name = b.get("name") or ""
        pr = prs.get(name) or {}
        branches.append(
            BranchInfo(
                name=name,
                is_remote=True,
                tip_sha=b.get("tip_sha"),
                tip_date=b.get("tip_date"),
                tip_subject=b.get("tip_subject"),
                ahead=b.get("ahead"),
                behind=b.get("behind"),
                merged_into_main=b.get("merged_into_main"),
                first_commit_date=b.get("tip_date"),
                pr_url=pr.get("url"),
                pr_number=pr.get("number"),
                pr_state=pr.get("state"),
            )
        )

    commit = (GIT_SHA or "").strip() or snap.get("main_sha")
    short = commit[:7] if commit else None
    return GitSnapshot(
        available=True,
        branch=(DEPLOY_BRANCH or "").strip() or "staging",
        commit=commit,
        short_commit=short,
        commit_subject=snap.get("main_subject") if commit == snap.get("main_sha") else None,
        commit_date=snap.get("main_date") if commit == snap.get("main_sha") else None,
        dirty_files=[],
        main_sha=snap.get("main_sha"),
        branches=branches,
        source="github_api",
    )


def _main_ref() -> str | None:
    if _run(["git", "rev-parse", "--verify", "origin/main"]):
        return "origin/main"
    if _run(["git", "rev-parse", "--verify", "main"]):
        return "main"
    return None


def _ahead_behind(branch_ref: str, main_ref: str) -> tuple[int | None, int | None]:
    out = _run(["git", "rev-list", "--left-right", "--count", f"{main_ref}...{branch_ref}"])
    if not out:
        return None, None
    parts = out.split()
    if len(parts) != 2:
        return None, None
    try:
        behind, ahead = int(parts[0]), int(parts[1])
        return ahead, behind
    except ValueError:
        return None, None


def _is_ancestor_local(tip: str, main_ref: str) -> bool | None:
    try:
        completed = subprocess.run(
            ["git", "merge-base", "--is-ancestor", tip, main_ref],
            cwd=str(repo_root()),
            capture_output=True,
            timeout=_GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    return None


def _branch_tip_meta(ref: str) -> tuple[str | None, str | None, str | None]:
    out = _run(["git", "log", "-1", "--format=%H%n%ci%n%s", ref])
    if not out:
        return None, None, None
    lines = out.split("\n", 2)
    if len(lines) < 3:
        return None, None, None
    return lines[0].strip(), lines[1].strip(), lines[2].strip()


def _first_commit_date(ref: str, main_ref: str) -> str | None:
    out = _run(["git", "log", "--reverse", "--format=%ci", f"{main_ref}..{ref}"])
    if not out:
        tip = _run(["git", "log", "-1", "--format=%ci", ref])
        return tip
    return out.split("\n", 1)[0].strip()


def _list_feature_branch_names() -> list[tuple[str, bool]]:
    found: dict[str, bool] = {}
    local = _run(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"])
    if local:
        for name in local.splitlines():
            name = name.strip()
            if _FEATURE_RE.match(name):
                found[name] = False
    remote = _run(["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin/"])
    if remote:
        for ref in remote.splitlines():
            ref = ref.strip()
            if not ref.startswith("origin/") or ref == "origin/HEAD":
                continue
            name = ref[len("origin/") :]
            if name in {"main", "master"}:
                continue
            if _FEATURE_RE.match(name):
                if name not in found:
                    found[name] = True
    return sorted(found.items(), key=lambda x: x[0].lower())


def _prs_by_head() -> dict[str, dict]:
    raw = _run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "all",
            "--limit",
            "50",
            "--json",
            "number,title,url,state,headRefName",
        ],
        timeout=_GH_TIMEOUT,
    )
    if not raw:
        return {}
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    by_head: dict[str, dict] = {}
    for item in items:
        head = (item.get("headRefName") or "").strip()
        if head and head not in by_head:
            by_head[head] = item
    return by_head


def _collect_via_local_git() -> GitSnapshot:
    if _run(["git", "rev-parse", "--is-inside-work-tree"]) != "true":
        return GitSnapshot(available=False, error="Not a git work tree", source="local_git")

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    commit = _run(["git", "rev-parse", "HEAD"])
    short = commit[:7] if commit else None
    subject = _run(["git", "log", "-1", "--format=%s"])
    date = _run(["git", "log", "-1", "--format=%ci"])
    dirty_raw = _run(["git", "status", "--porcelain"])
    dirty = [line for line in (dirty_raw or "").splitlines() if line.strip()]

    main_ref = _main_ref()
    main_sha = _run(["git", "rev-parse", main_ref]) if main_ref else None
    prs = _prs_by_head()

    branches: list[BranchInfo] = []
    for name, is_remote in _list_feature_branch_names():
        ref = f"origin/{name}" if is_remote else name
        tip_sha, tip_date, tip_subject = _branch_tip_meta(ref)
        ahead = behind = None
        merged: bool | None = None
        first = None
        if main_ref and tip_sha:
            ahead, behind = _ahead_behind(ref, main_ref)
            merged = _is_ancestor_local(tip_sha, main_ref)
            first = _first_commit_date(ref, main_ref)
        pr = prs.get(name) or {}
        branches.append(
            BranchInfo(
                name=name,
                is_remote=is_remote,
                tip_sha=tip_sha,
                tip_date=tip_date,
                tip_subject=tip_subject,
                ahead=ahead,
                behind=behind,
                merged_into_main=merged,
                first_commit_date=first,
                pr_url=pr.get("url"),
                pr_number=pr.get("number"),
                pr_state=pr.get("state"),
            )
        )

    return GitSnapshot(
        available=True,
        branch=branch,
        commit=commit,
        short_commit=short,
        commit_subject=subject,
        commit_date=date,
        dirty_files=dirty,
        main_sha=main_sha,
        branches=branches,
        source="local_git",
    )


def collect_git_snapshot() -> GitSnapshot:
    """Prefer local git when available; otherwise GitHub API (staging)."""
    local = _collect_via_local_git()
    if local.available:
        return local
    gh = _collect_via_github()
    if gh is not None:
        return gh
    return local


def resolve_ref_sha(*refs: str) -> str | None:
    """Return the first resolvable commit SHA among refs (branch names or SHAs)."""
    for ref in refs:
        ref = (ref or "").strip()
        if not ref:
            continue
        sha = _run(["git", "rev-parse", "--verify", ref])
        if sha:
            return sha
    # GitHub fallback: match branch name from last GitHub snapshot path
    token = (GITHUB_TOKEN or "").strip()
    owner_repo = _github_owner_repo()
    if token and owner_repo:
        owner, repo = owner_repo
        from app.releases.github_api import _request

        for ref in refs:
            ref = (ref or "").strip()
            if not ref:
                continue
            name = ref[len("origin/") :] if ref.startswith("origin/") else ref
            data = _request(
                f"https://api.github.com/repos/{owner}/{repo}/commits/{name}",
                token,
            )
            if isinstance(data, dict) and data.get("sha"):
                return data["sha"]
    return None


def commits_between(older_sha: str, newer_sha: str, *, limit: int = 40) -> list[str]:
    """Subjects on newer not in older. Empty list if unknown."""
    if not older_sha or not newer_sha:
        return []
    out = _run(["git", "log", "--oneline", f"--max-count={limit}", f"{older_sha}..{newer_sha}"])
    if out:
        return [line for line in out.splitlines() if line.strip()]

    token = (GITHUB_TOKEN or "").strip()
    owner_repo = _github_owner_repo()
    if not token or not owner_repo:
        return []
    owner, repo = owner_repo
    from app.releases.github_api import _request
    import urllib.parse

    data = _request(
        f"https://api.github.com/repos/{owner}/{repo}/compare/"
        f"{urllib.parse.quote(older_sha, safe='')}...{urllib.parse.quote(newer_sha, safe='')}",
        token,
    )
    if not isinstance(data, dict):
        return []
    lines: list[str] = []
    for c in (data.get("commits") or [])[:limit]:
        sha = (c.get("sha") or "")[:7]
        msg = ((c.get("commit") or {}).get("message") or "").split("\n", 1)[0]
        if sha or msg:
            lines.append(f"{sha} {msg}".strip())
    return lines


def is_ancestor(commit: str, maybe_descendant: str) -> bool | None:
    if not commit or not maybe_descendant:
        return None
    local = _is_ancestor_local(commit, maybe_descendant)
    if local is not None and _run(["git", "rev-parse", "--is-inside-work-tree"]) == "true":
        return local

    token = (GITHUB_TOKEN or "").strip()
    owner_repo = _github_owner_repo()
    if not token or not owner_repo:
        return local
    owner, repo = owner_repo
    from app.releases.github_api import compare_contains

    return compare_contains(owner, repo, token, commit, maybe_descendant)
