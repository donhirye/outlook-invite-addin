"""Read/write immutable local issue archive folders."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from newsletter_archive.config import (
    NEWSLETTER_ISSUES_DIR,
    artifact_name,
    ensure_local_dirs,
    issue_basename,
)
from newsletter_archive.models import IssueMetadata
from newsletter_archive.naming import series_slug_from_subject

logger = logging.getLogger(__name__)


class ArchiveConflictError(RuntimeError):
    pass


def issue_folder_path(subject: str, issue_date: str, root: Path | None = None) -> Path:
    base = root or NEWSLETTER_ISSUES_DIR
    return base / issue_basename(subject, issue_date)


def resolve_issue_dir(path: str | Path) -> Path:
    """Accept an issue folder path or a path to any artifact inside it."""
    p = Path(path).resolve()
    if p.is_file():
        p = p.parent
    if not p.is_dir():
        raise FileNotFoundError(f"Issue folder not found: {p}")
    return p


def load_metadata(issue_dir: Path) -> IssueMetadata:
    issue_dir = resolve_issue_dir(issue_dir)
    candidates = sorted(issue_dir.glob("*_Metadata.json"))
    if not candidates:
        raise FileNotFoundError(f"No metadata JSON in {issue_dir}")
    # Prefer metadata whose stem matches the folder name.
    folder = issue_dir.name
    meta_path = candidates[0]
    for c in candidates:
        if c.name.startswith(folder) or c.stem.replace("_Metadata", "") == folder:
            meta_path = c
            break
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    return IssueMetadata.from_dict(data)


def load_source_html(issue_dir: Path) -> str:
    issue_dir = resolve_issue_dir(issue_dir)
    html_files = sorted(issue_dir.glob("*_Source.html"))
    if not html_files:
        raise FileNotFoundError(f"No *_Source.html in {issue_dir}")
    return html_files[0].read_text(encoding="utf-8")


def write_source_archive(
    *,
    subject: str,
    issue_date: str,
    metadata: IssueMetadata,
    html: str,
    eml_bytes: bytes | None,
    root: Path | None = None,
) -> Path:
    """Write immutable source files. Refuses to overwrite different content."""
    ensure_local_dirs()
    series = series_slug_from_subject(subject)
    folder_name = issue_basename(subject, issue_date)
    metadata.newsletter_series = series
    metadata.folder_name = folder_name

    folder = issue_folder_path(subject, issue_date, root=root)
    folder.mkdir(parents=True, exist_ok=True)

    html_name = artifact_name(subject, issue_date, "html")
    meta_name = artifact_name(subject, issue_date, "metadata")
    eml_name = artifact_name(subject, issue_date, "eml")

    html_path = folder / html_name
    meta_path = folder / meta_name
    eml_path = folder / eml_name

    if html_path.exists():
        existing = html_path.read_text(encoding="utf-8")
        from newsletter_archive.hashing import content_hash

        if content_hash(existing) != metadata.source_content_hash:
            raise ArchiveConflictError(
                f"Refusing to overwrite differing HTML archive at {html_path}"
            )
        logger.info("Local HTML already present (same hash): %s", html_path.name)
    else:
        html_path.write_text(html, encoding="utf-8", newline="\n")

    meta_path.write_text(
        json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    if eml_bytes is not None:
        if eml_path.exists():
            if eml_path.read_bytes() != eml_bytes:
                raise ArchiveConflictError(
                    f"Refusing to overwrite differing EML archive at {eml_path}"
                )
        else:
            eml_path.write_bytes(eml_bytes)
        metadata.eml_preserved = True
        meta_path.write_text(
            json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    elif not eml_path.exists():
        note = folder / f"{folder_name}_Source.eml.MISSING.txt"
        note.write_text(
            (metadata.eml_limitation or "Faithful .eml could not be produced.")
            + "\nHTML snapshot is the generator source of truth.\n",
            encoding="utf-8",
        )

    metadata.local_folder = str(folder)
    meta_path.write_text(
        json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    logger.info(
        "Wrote local archive folder=%s gmail_id=%s hash=%s",
        folder.name,
        metadata.gmail_message_id,
        metadata.source_content_hash[:12],
    )
    return folder
