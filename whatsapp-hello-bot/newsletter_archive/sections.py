"""Generate cleaned Markdown sections from archived newsletter HTML."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Iterable

from newsletter_archive.models import IssueMetadata

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - dependency note
    BeautifulSoup = None  # type: ignore


@dataclass
class Section:
    heading: str
    body_lines: list[str]


_SKIP_TEXT = re.compile(
    r"^(share|tweet|forward|view\s+in\s+browser|unsubscribe|manage\s+preferences|"
    r"open\s+in\s+smore|add\s+to\s+calendar|like\s+this|comment)\b",
    re.I,
)


def _require_bs4():
    if BeautifulSoup is None:
        raise RuntimeError(
            "beautifulsoup4 is required. pip install -r requirements-newsletter.txt"
        )


def _clean_inline(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _iter_blocks(soup) -> Iterable[tuple[str, str]]:
    """Yield (kind, text) where kind is heading|para|list|link."""
    for el in soup.find_all(
        ["h1", "h2", "h3", "h4", "h5", "p", "li", "td", "th", "a", "div", "span"]
    ):
        name = el.name.lower()
        if name in {"script", "style", "noscript"}:
            continue
        # Prefer leaf-ish text for div/span only when they look like headings
        text = _clean_inline(el.get_text(" ", strip=True))
        if not text or len(text) < 2:
            continue
        if _SKIP_TEXT.match(text):
            continue
        if name in {"h1", "h2", "h3", "h4", "h5"}:
            yield ("heading", text)
        elif name in {"li"}:
            yield ("list", text)
        elif name == "a" and el.get("href"):
            href = el.get("href") or ""
            if href.startswith("mailto:") or href.startswith("http"):
                yield ("link", f"[{text}]({href})")
        elif name in {"p", "td", "th"}:
            yield ("para", text)
        elif name in {"div", "span"}:
            # Keep short bold-looking banners as headings when alone
            if el.find(["h1", "h2", "h3", "h4", "p", "li"]):
                continue
            if len(text) <= 80 and text.isupper():
                yield ("heading", text.title())


def html_to_sections(html: str) -> list[Section]:
    _require_bs4()
    try:
        soup = BeautifulSoup(html or "", "lxml")
    except Exception:
        soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    sections: list[Section] = []
    current = Section(heading="Newsletter", body_lines=[])
    seen_lines: set[str] = set()

    for kind, text in _iter_blocks(soup):
        key = text.lower()
        if key in seen_lines:
            continue
        # Soft dedupe only exact repeats
        if kind == "heading":
            if current.body_lines or current.heading != "Newsletter":
                sections.append(current)
            current = Section(heading=text, body_lines=[])
            seen_lines.add(key)
            continue
        if kind == "list":
            line = f"- {text}"
        else:
            line = text
        if line.lower() in seen_lines:
            continue
        seen_lines.add(line.lower())
        current.body_lines.append(line)

    if current.body_lines or current.heading != "Newsletter":
        sections.append(current)

    # Drop empty / tiny junk sections
    cleaned: list[Section] = []
    for sec in sections:
        body = [b for b in sec.body_lines if b.strip()]
        if not body and sec.heading == "Newsletter":
            continue
        cleaned.append(Section(heading=sec.heading, body_lines=body))
    return cleaned or [Section(heading="Newsletter", body_lines=["(No extractable text)"])]


def sections_to_markdown(sections: list[Section], metadata: IssueMetadata) -> str:
    lines = [
        f"# {metadata.subject or 'Crone PTSA Newsletter'}",
        "",
        f"- Issue date: `{metadata.issue_date}` (basis: {metadata.date_basis})",
        f"- Received: `{metadata.received_at}`",
        f"- Gmail message id: `{metadata.gmail_message_id}`",
        f"- Source content hash: `{metadata.source_content_hash}`",
    ]
    if metadata.smore_url:
        lines.append(f"- Smore URL (reference only; not used to rebuild content): {metadata.smore_url}")
    lines.extend(
        [
            "",
            "> Draft archive extract for human review. Not published to the chatbot/RAG.",
            "",
        ]
    )
    for sec in sections:
        lines.append(f"## {sec.heading}")
        lines.append("")
        if sec.body_lines:
            lines.extend(sec.body_lines)
        else:
            lines.append("_No body text captured under this heading._")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate_cleaned_sections_markdown(html: str, metadata: IssueMetadata) -> str:
    return sections_to_markdown(html_to_sections(html), metadata)
