"""Build retrieval chunks from archived newsletter HTML / cleaned sections."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
_MIN_BODY_CHARS = 40


def _issue_date_from_folder(folder: Path, metadata: dict[str, Any]) -> str:
    for key in ("issue_date", "publication_date", "published_date"):
        val = str(metadata.get(key) or "").strip()
        if val:
            return val[:10]
    # Folder suffix ..._YYYY-MM-DD
    m = re.search(r"(20\d{2}-\d{2}-\d{2})$", folder.name)
    return m.group(1) if m else ""


def _source_label(folder: Path, metadata: dict[str, Any], issue_date: str) -> str:
    subject = str(metadata.get("subject") or "").strip()
    if "PTSA" in folder.name.upper() or "ptsa" in subject.lower():
        series = "Crone PTSA Newsletter"
    elif "Summer" in folder.name:
        series = "Crone Summer Newsletter"
    else:
        series = "Crone's Weekly Newsletter"
    if issue_date:
        return f"{series} - {issue_date}"
    return series


def _chunks_from_sections(
    sections: list[tuple[str, str]],
    *,
    folder: Path,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    issue_date = _issue_date_from_folder(folder, metadata)
    source = _source_label(folder, metadata, issue_date)
    out: list[dict[str, Any]] = []
    for heading, body in sections:
        heading = (heading or "").strip() or "Newsletter"
        body = (body or "").strip()
        if len(body) < _MIN_BODY_CHARS:
            continue
        # Skip giant noisy preamble dumps labeled Newsletter when shorter
        # titled sections exist — still keep if it's the only content.
        text = f"Section: {heading}\nIssue: {issue_date or folder.name}\n{body}"
        out.append(
            {
                "text": text,
                "metadata": {
                    "heading": heading,
                    "issue_folder": folder.name,
                    "issue_date": issue_date,
                    "source": source,
                    "source_url": str(metadata.get("smore_url") or ""),
                },
            }
        )
    return out


def parse_cleaned_sections_markdown(md: str) -> list[tuple[str, str]]:
    """Split *_Cleaned_Sections.md on ## headings → (heading, body)."""
    text = (md or "").strip()
    if not text:
        return []
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        body = text.strip()
        return [("Newsletter", body)] if body else []
    sections: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        # Drop archive boilerplate under the first mega dump when a real
        # titled section follows; keep all ## blocks with enough body.
        if heading.lower() in {"newsletter"} and len(body) > 2500:
            # Prefer later structured sections; keep a truncated lead-in only
            # if no other sections will be emitted.
            sections.append((heading, body[:1200]))
            continue
        sections.append((heading, body))
    # If we only kept a truncated Newsletter and nothing else usable, restore.
    usable = [(h, b) for h, b in sections if h.lower() != "newsletter" or len(b) >= _MIN_BODY_CHARS]
    if not usable and sections:
        return sections
    return usable


def chunk_issue_folder(folder: Path) -> list[dict[str, Any]]:
    """Build section chunks for one archived issue folder."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    meta_path = next(folder.glob("*_Metadata.json"), None)
    metadata: dict[str, Any] = {}
    if meta_path and meta_path.exists():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                metadata = loaded
        except (json.JSONDecodeError, OSError):
            logger.exception("Failed reading metadata %s", meta_path)

    cleaned = next(folder.glob("*_Cleaned_Sections.md"), None)
    if cleaned and cleaned.exists():
        sections = parse_cleaned_sections_markdown(
            cleaned.read_text(encoding="utf-8")
        )
        return _chunks_from_sections(sections, folder=folder, metadata=metadata)

    html_path = next(folder.glob("*_Source.html"), None)
    if not html_path or not html_path.exists():
        return []
    try:
        from newsletter_archive.sections import html_to_sections
    except Exception:
        logger.exception("newsletter_archive.sections unavailable for %s", folder)
        return []
    try:
        html = html_path.read_text(encoding="utf-8", errors="ignore")
        parsed = html_to_sections(html)
    except Exception:
        logger.exception("Failed sectioning HTML for %s", folder)
        return []
    sections = [
        (sec.heading, "\n".join(sec.body_lines).strip()) for sec in parsed
    ]
    return _chunks_from_sections(sections, folder=folder, metadata=metadata)


def collect_section_chunks(issues_root: Path) -> list[dict[str, Any]]:
    """Walk newsletter_archive/issues and collect all section chunks."""
    root = Path(issues_root)
    if not root.is_dir():
        return []
    all_chunks: list[dict[str, Any]] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        if folder.name.startswith(".") or folder.name.upper().startswith("TMP"):
            continue
        if folder.name.lower() == "new folder":
            continue
        issue_chunks = chunk_issue_folder(folder)
        all_chunks.extend(issue_chunks)
        logger.info(
            "Section chunks from %s: %s", folder.name, len(issue_chunks)
        )
    for i, chunk in enumerate(all_chunks):
        chunk["id"] = i
    return all_chunks
