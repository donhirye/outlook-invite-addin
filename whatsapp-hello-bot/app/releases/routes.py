"""Releases dashboard routes (local DEV + staging admin). Never registered in production.

Read-only for Git / Cloud Run / deploys. The only write is experiment decisions
to the staging GCS registry (or local file in DEV).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.releases.dashboard import clear_cache, get_dashboard
from app.releases.registry import record_decision

logger = logging.getLogger(__name__)


def register_releases(
    app: FastAPI,
    *,
    is_logged_in: Callable[[Request], bool],
    templates: Jinja2Templates,
    branding: Callable[[], dict[str, Any]],
) -> None:
    @app.get("/admin/releases", response_class=HTMLResponse)
    async def admin_releases(request: Request) -> Response:
        if not is_logged_in(request):
            return RedirectResponse(url="/admin", status_code=303)
        data = get_dashboard()
        return templates.TemplateResponse(
            request,
            "admin_releases.html",
            {
                **branding(),
                "dash": data,
                "active_nav": "releases",
            },
        )

    @app.post("/admin/releases/refresh")
    async def admin_releases_refresh(request: Request) -> Response:
        if not is_logged_in(request):
            return RedirectResponse(url="/admin", status_code=303)
        clear_cache()
        get_dashboard(force=True)
        return RedirectResponse(url="/admin/releases", status_code=303)

    @app.post("/admin/releases/decision")
    async def admin_releases_decision(
        request: Request,
        experiment_id: str = Form(...),
        decision: str = Form(...),
        reason: str = Form(""),
        commit_id: str = Form(""),
    ) -> Response:
        if not is_logged_in(request):
            return RedirectResponse(url="/admin", status_code=303)
        try:
            record_decision(
                experiment_id=experiment_id.strip(),
                decision=decision.strip(),
                reason=reason or "",
                commit_id=commit_id or "",
                actor="admin",
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            logger.warning("Decision save failed: %s", exc)
        clear_cache()
        return RedirectResponse(url="/admin/releases", status_code=303)
