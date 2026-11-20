"""Read-only Cloud Run service/revision probes (no deploys, no writes).

Uses Application Default Credentials on Cloud Run (staging-runtime SA with
roles/run.viewer). Never returns env var secret values — only names needed
for GIT_SHA / labels / image / traffic.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_TIMEOUT = 15
_SCOPES = ("https://www.googleapis.com/auth/cloud-platform.read-only",)


def _access_token() -> str | None:
    try:
        import google.auth  # type: ignore
        import google.auth.transport.requests  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("google.auth unavailable for Cloud Run probe: %s", exc)
        return None
    try:
        creds, _ = google.auth.default(scopes=list(_SCOPES))
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not refresh ADC for Cloud Run probe: %s", exc)
        return None


def _get_json(url: str, token: str) -> dict[str, Any] | None:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "whatsapp-faq-bot-releases",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("Cloud Run GET failed for %s: %s", url, exc)
        return None


def _git_sha_from_revision(rev: dict[str, Any]) -> str | None:
    """Extract GIT_SHA from revision env or labels — never other env values."""
    meta = rev.get("metadata") or {}
    labels = meta.get("labels") or {}
    for key in ("git-sha", "git_sha", "commit-sha"):
        val = labels.get(key)
        if isinstance(val, str) and len(val.strip()) >= 7:
            return val.strip()

    spec = rev.get("spec") or {}
    containers = spec.get("containers") or []
    if not containers:
        return None
    for env in containers[0].get("env") or []:
        if not isinstance(env, dict):
            continue
        if (env.get("name") or "") == "GIT_SHA":
            val = env.get("value")
            if isinstance(val, str) and len(val.strip()) >= 7:
                return val.strip()
            return None
    return None


def _image_from_revision(rev: dict[str, Any]) -> str | None:
    containers = ((rev.get("spec") or {}).get("containers")) or []
    if not containers:
        return None
    image = containers[0].get("image")
    return image.strip() if isinstance(image, str) and image.strip() else None


def describe_serving(
    *,
    project: str,
    region: str,
    service: str,
) -> dict[str, Any]:
    """Return live traffic split + primary serving revision/image/git_sha."""
    out: dict[str, Any] = {
        "available": False,
        "source": "cloudrun",
        "project": project,
        "region": region,
        "service": service,
        "status": "Not Verified",
        "traffic": [],
        "split": False,
        "revision": None,
        "image": None,
        "git_sha": None,
        "percent": None,
        "detail": None,
    }
    if not project or not region or not service:
        out["detail"] = "Cloud Run project/region/service not configured"
        return out

    token = _access_token()
    if not token:
        out["detail"] = "No credentials for Cloud Run read"
        return out

    base = f"https://run.googleapis.com/v1/projects/{project}/locations/{region}"
    svc = _get_json(f"{base}/services/{service}", token)
    if not svc:
        out["detail"] = f"Could not describe service {service}"
        return out

    status = svc.get("status") or {}
    traffic_raw = status.get("traffic") or []
    traffic: list[dict[str, Any]] = []
    for t in traffic_raw:
        if not isinstance(t, dict):
            continue
        pct = t.get("percent")
        rev = (t.get("revisionName") or "").strip() or None
        if pct is None and not rev:
            continue
        traffic.append(
            {
                "revision": rev,
                "percent": int(pct) if pct is not None else None,
                "latest_revision": bool(t.get("latestRevision")),
            }
        )

    # Primary = highest percent with a revision name.
    primary = None
    if traffic:
        ranked = sorted(
            [x for x in traffic if x.get("revision")],
            key=lambda x: (x.get("percent") is not None, x.get("percent") or 0),
            reverse=True,
        )
        primary = ranked[0] if ranked else None

    if not primary:
        # Fall back to latestReadyRevisionName when traffic block is empty/odd.
        ready = (status.get("latestReadyRevisionName") or "").strip()
        if ready:
            primary = {"revision": ready, "percent": 100, "latest_revision": True}
            traffic = [primary]

    if not primary or not primary.get("revision"):
        out["detail"] = "No serving revision in Cloud Run status"
        out["traffic"] = traffic
        return out

    rev_name = primary["revision"]
    rev = _get_json(f"{base}/revisions/{rev_name}", token)
    image = _image_from_revision(rev) if rev else None
    git_sha = _git_sha_from_revision(rev) if rev else None

    split = len([t for t in traffic if (t.get("percent") or 0) > 0]) > 1
    out.update(
        {
            "available": True,
            "status": "Live",
            "traffic": traffic,
            "split": split,
            "revision": rev_name,
            "image": image,
            "git_sha": git_sha,
            "percent": primary.get("percent"),
            "detail": None,
            "ok": True,
        }
    )
    return out
