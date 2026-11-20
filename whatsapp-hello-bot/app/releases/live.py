"""Read-only HTTP probes of staging/production /health (no secrets, no gcloud)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_TIMEOUT = 8


def probe_health(base_url: str | None) -> dict[str, Any]:
    if not base_url or not base_url.strip():
        return {
            "available": False,
            "source": "live",
            "status": "Not Verified",
            "detail": "Base URL not configured",
        }
    root = base_url.strip().rstrip("/")
    url = f"{root}/health"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            code = resp.status
    except urllib.error.HTTPError as exc:
        return {
            "available": False,
            "source": "live",
            "status": "Not Verified",
            "detail": f"HTTP {exc.code} from /health",
            "url": url,
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("health probe failed for %s: %s", url, exc)
        return {
            "available": False,
            "source": "live",
            "status": "Not Verified",
            "detail": "Could not reach /health",
            "url": url,
        }

    git_sha = None
    app_env = None
    health_status = None
    try:
        payload = json.loads(body)
        if isinstance(payload, dict):
            health_status = payload.get("status")
            git_sha = (payload.get("git_sha") or "").strip() or None
            app_env = (payload.get("app_env") or "").strip() or None
    except json.JSONDecodeError:
        payload = None

    ok = code == 200 and (health_status == "ok" or health_status is None)
    return {
        "available": True,
        "source": "live",
        "status": "Live" if ok else "Not Verified",
        "http_status": code,
        "health_status": health_status or "Unknown",
        "git_sha": git_sha or "Unknown",
        "app_env": app_env or "Unknown",
        "url": url,
        "ok": ok,
    }
