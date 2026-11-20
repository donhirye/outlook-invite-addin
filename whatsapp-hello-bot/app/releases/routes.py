"""Releases dashboard routes (local DEV + staging admin). Never registered in production."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.releases.dashboard import clear_cache, get_dashboard


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
