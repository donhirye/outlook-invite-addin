"""Local git / gh probes for the Releases dashboard. Never raises to callers."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.config import BASE_DIR

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

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


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


def _is_ancestor(tip: str, main_ref: str) -> bool | None:
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
        # no commits ahead of main — use tip date
        tip = _run(["git", "log", "-1", "--format=%ci", ref])
        return tip
    return out.split("\n", 1)[0].strip()


def _list_feature_branch_names() -> list[tuple[str, bool]]:
    """Return (short_name, is_remote) for feature-like branches."""
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
                # Prefer local entry when both exist
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


def collect_git_snapshot() -> GitSnapshot:
    if _run(["git", "rev-parse", "--is-inside-work-tree"]) != "true":
        return GitSnapshot(available=False, error="Not a git work tree")

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
            merged = _is_ancestor(tip_sha, main_ref)
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
    )


def commits_between(older_sha: str, newer_sha: str, *, limit: int = 40) -> list[str]:
    """Subjects on newer not in older. Empty list if unknown."""
    if not older_sha or not newer_sha:
        return []
    out = _run(["git", "log", "--oneline", f"--max-count={limit}", f"{older_sha}..{newer_sha}"])
    if not out:
        return []
    return [line for line in out.splitlines() if line.strip()]


def is_ancestor(commit: str, maybe_descendant: str) -> bool | None:
    if not commit or not maybe_descendant:
        return None
    return _is_ancestor(commit, maybe_descendant)
