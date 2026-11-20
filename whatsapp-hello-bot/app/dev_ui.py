"""Local DEV UI helpers (banner + Test Chat nav). Wired only when APP_ENV=development."""

from __future__ import annotations

import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

BANNER_HTML = (
    "<style>body{padding-top:2.9rem !important;}</style>"
    '<div id="dev-banner" role="alert" style="position:fixed;top:0;left:0;right:0;'
    "z-index:2147483647;background:#0b3d91;color:#fff;font:700 .95rem/1.2 system-ui,"
    "'Segoe UI',sans-serif;text-align:center;padding:.6rem .75rem;"
    'border-bottom:3px solid #061f4a;">'
    "LOCAL DEV ENVIRONMENT &mdash; laptop only. WhatsApp sending is disabled. "
    "Data lives under data/dev/ (not GCS).</div>"
)
TEST_CHAT_PATH = "/admin/test-chat"
RELEASES_PATH = "/admin/releases"
_TEST_CHAT_LINK = f'<a href="{TEST_CHAT_PATH}">Test Chat</a>'
_RELEASES_LINK = f'<a href="{RELEASES_PATH}">Releases</a>'
_LOGOUT_LINK = '<a href="/admin/logout">'
_BODY_RE = re.compile(r"(<body[^>]*>)", re.IGNORECASE)
_TITLE_RE = re.compile(r"(<title[^>]*>)", re.IGNORECASE)


def decorate_html(html: str) -> str:
    if 'id="dev-banner"' not in html:
        html = _BODY_RE.sub(lambda m: m.group(1) + BANNER_HTML, html, count=1)
        html = _TITLE_RE.sub(lambda m: m.group(1) + "[LOCAL DEV] ", html, count=1)
    if _LOGOUT_LINK in html:
        inject = ""
        if RELEASES_PATH not in html:
            inject += _RELEASES_LINK
        if TEST_CHAT_PATH not in html:
            inject += _TEST_CHAT_LINK
        if inject:
            html = html.replace(_LOGOUT_LINK, inject + _LOGOUT_LINK, 1)
    return html


class DevHtmlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        response = await call_next(request)
        if not response.headers.get("content-type", "").startswith("text/html"):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        content = decorate_html(body.decode("utf-8", errors="replace")).encode("utf-8")
        new_response = Response(content=content, status_code=response.status_code)
        new_response.raw_headers = [
            (k, v) for k, v in response.raw_headers if k.lower() != b"content-length"
        ] + [(b"content-length", str(len(content)).encode())]
        return new_response
