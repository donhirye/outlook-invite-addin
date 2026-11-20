"""Staging-only helpers.

Everything here is wired in by ``app.main`` only when ``APP_ENV=staging``. In
production this module is imported by nothing at runtime.
"""

from __future__ import annotations

import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

BANNER_HTML = (
    "<style>body{padding-top:2.9rem !important;}</style>"
    '<div id="staging-banner" role="alert" style="position:fixed;top:0;left:0;right:0;'
    "z-index:2147483647;background:#ffcc00;color:#111;font:700 .95rem/1.2 system-ui,"
    "'Segoe UI',sans-serif;text-align:center;padding:.6rem .75rem;"
    'border-bottom:3px solid #111;">'
    "STAGING ENVIRONMENT &mdash; not production. WhatsApp sending is disabled and "
    "all data here is a separate copy.</div>"
)
TEST_CHAT_PATH = "/admin/test-chat"
RELEASES_PATH = "/admin/releases"
_TEST_CHAT_LINK = f'<a href="{TEST_CHAT_PATH}">Test Chat</a>'
_RELEASES_LINK = f'<a href="{RELEASES_PATH}">Releases</a>'
_LOGOUT_LINK = '<a href="/admin/logout">'
_BODY_RE = re.compile(r"(<body[^>]*>)", re.IGNORECASE)
_TITLE_RE = re.compile(r"(<title[^>]*>)", re.IGNORECASE)


def decorate_html(html: str) -> str:
    """Add the STAGING banner, title prefix, Releases + Test Chat nav links."""
    if 'id="staging-banner"' not in html:
        html = _BODY_RE.sub(lambda m: m.group(1) + BANNER_HTML, html, count=1)
        html = _TITLE_RE.sub(lambda m: m.group(1) + "[STAGING] ", html, count=1)
    inject = ""
    if RELEASES_PATH not in html:
        inject += _RELEASES_LINK
    if TEST_CHAT_PATH not in html:
        inject += _TEST_CHAT_LINK
    if inject and _LOGOUT_LINK in html:
        html = html.replace(_LOGOUT_LINK, inject + _LOGOUT_LINK, 1)
    return html


class StagingHtmlMiddleware(BaseHTTPMiddleware):
    """Decorate every HTML response (all admin pages) with the STAGING banner."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        response = await call_next(request)
        if not response.headers.get("content-type", "").startswith("text/html"):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        content = decorate_html(body.decode("utf-8", errors="replace")).encode("utf-8")
        new_response = Response(content=content, status_code=response.status_code)
        # Keep every original header (including repeated Set-Cookie), fix the length.
        new_response.raw_headers = [
            (k, v) for k, v in response.raw_headers if k.lower() != b"content-length"
        ] + [(b"content-length", str(len(content)).encode())]
        return new_response
