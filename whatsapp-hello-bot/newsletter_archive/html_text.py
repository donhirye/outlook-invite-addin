"""HTML → plain text that keeps actionable hrefs as markdown links."""

from __future__ import annotations

import re
from html import unescape

try:
    from bs4 import BeautifulSoup
    from bs4.element import NavigableString, Tag
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore
    NavigableString = object  # type: ignore
    Tag = object  # type: ignore


def _require_bs4() -> None:
    if BeautifulSoup is None:
        raise RuntimeError(
            "beautifulsoup4 is required. pip install -r requirements-newsletter.txt"
        )


def link_markdown(text: str, href: str) -> str:
    """Build a markdown link; fall back to bare URL or text when incomplete."""
    label = unescape(re.sub(r"\s+", " ", (text or "").strip()))
    url = unescape((href or "").strip())
    if url.startswith(("http://", "https://", "mailto:")):
        if label:
            return f"[{label}]({url})"
        return url
    return label or url


def rewrite_anchor_tags(soup) -> None:
    """Replace every <a href> in-place with markdown / plain text NavigableString."""
    for a in list(soup.find_all("a")):
        if not isinstance(a, Tag):
            continue
        href = (a.get("href") or "").strip()
        label = a.get_text(" ", strip=True)
        replacement = link_markdown(label, href)
        a.replace_with(NavigableString(replacement))


def element_text_with_links(el) -> str:
    """Visible text for one element, with nested anchors as [text](url)."""
    _require_bs4()
    if el is None:
        return ""
    # Copy so we do not mutate the tree used by other walkers.
    clone = BeautifulSoup(str(el), "html.parser")
    # str(el) wraps a fragment; prefer the mirrored tag when present.
    root = clone.find(el.name) if getattr(el, "name", None) else clone
    target = root or clone
    rewrite_anchor_tags(target)
    text = unescape(target.get_text(" ", strip=True))
    return re.sub(r"\s+", " ", text).strip()


def html_to_text_preserve_links(html: str) -> str:
    """Full-document plain text with markdown links preserved for the extractor."""
    _require_bs4()
    try:
        soup = BeautifulSoup(html or "", "lxml")
    except Exception:
        soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    rewrite_anchor_tags(soup)
    text = soup.get_text("\n", strip=True)
    text = text.replace("\u200c", "").replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?:\u00ad|\u200b|\u200c|\s){8,}", " ", text)
    return text.strip()
