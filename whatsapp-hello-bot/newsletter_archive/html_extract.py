"""Extract HTML/text bodies and links from Gmail MIME / archived HTML."""

from __future__ import annotations

import base64
import re
from email import policy
from email.message import Message
from email.parser import BytesParser
from typing import Any

_SMORE_RE = re.compile(
    r"https?://(?:www\.)?(?:app\.)?smore\.com/[^\s\"'<>]+",
    re.IGNORECASE,
)


def b64url_decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def walk_gmail_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten Gmail API message payload parts."""
    out: list[dict[str, Any]] = []
    stack = [payload]
    while stack:
        part = stack.pop()
        out.append(part)
        for child in part.get("parts") or []:
            stack.append(child)
    return out


def extract_bodies_from_gmail_payload(payload: dict[str, Any]) -> tuple[str, str]:
    """Return (html, plain_text) from a Gmail ``payload`` dict.

    Prefers text/html; falls back to text/plain wrapped as minimal HTML.
    Never fetches external URLs (including Smore).
    """
    html_parts: list[str] = []
    text_parts: list[str] = []
    for part in walk_gmail_parts(payload):
        mime = (part.get("mimeType") or "").lower()
        body = part.get("body") or {}
        data = body.get("data")
        if not data:
            continue
        try:
            raw = b64url_decode(data).decode("utf-8", errors="replace")
        except Exception:
            continue
        if mime == "text/html":
            html_parts.append(raw)
        elif mime == "text/plain":
            text_parts.append(raw)

    html = "\n".join(html_parts).strip()
    plain = "\n".join(text_parts).strip()
    if not html and plain:
        escaped = (
            plain.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        html = f"<html><body><pre>{escaped}</pre></body></html>"
    return html, plain


def parse_raw_eml(raw_bytes: bytes) -> Message:
    return BytesParser(policy=policy.default).parsebytes(raw_bytes)


def extract_bodies_from_eml(msg: Message) -> tuple[str, str]:
    html_parts: list[str] = []
    text_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/html":
                html_parts.append(part.get_content())
            elif ctype == "text/plain":
                text_parts.append(part.get_content())
    else:
        ctype = msg.get_content_type()
        content = msg.get_content()
        if ctype == "text/html":
            html_parts.append(content)
        else:
            text_parts.append(content)
    html = "\n".join(str(p) for p in html_parts).strip()
    plain = "\n".join(str(p) for p in text_parts).strip()
    if not html and plain:
        escaped = (
            plain.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        html = f"<html><body><pre>{escaped}</pre></body></html>"
    return html, plain


def find_smore_url(*texts: str) -> str | None:
    for text in texts:
        if not text:
            continue
        match = _SMORE_RE.search(text)
        if match:
            return match.group(0).rstrip(").,];")
    return None


def header_value(headers: list[dict[str, str]], name: str) -> str:
    target = name.lower()
    for item in headers or []:
        if (item.get("name") or "").lower() == target:
            return item.get("value") or ""
    return ""
