"""Local idempotency index: Gmail message ID + content hash + series|date."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from newsletter_archive.config import NEWSLETTER_INDEX_PATH, ensure_local_dirs
from newsletter_archive.naming import issue_key


def load_index(path: Path | None = None) -> dict[str, Any]:
    ensure_local_dirs()
    index_path = path or NEWSLETTER_INDEX_PATH
    if not index_path.exists():
        return {
            "by_gmail_id": {},
            "by_issue_key": {},
            "by_content_hash": {},
        }
    data = json.loads(index_path.read_text(encoding="utf-8"))
    data.setdefault("by_gmail_id", {})
    data.setdefault("by_issue_key", {})
    data.setdefault("by_content_hash", {})
    # Migrate legacy by_issue_date if present (date-only keys collide across series).
    if "by_issue_date" in data and not data["by_issue_key"]:
        # Leave legacy map unused; new imports use by_issue_key only.
        pass
    return data


def save_index(data: dict[str, Any], path: Path | None = None) -> None:
    ensure_local_dirs()
    index_path = path or NEWSLETTER_INDEX_PATH
    index_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def lookup_conflicts(
    index: dict[str, Any],
    *,
    gmail_message_id: str,
    series_slug: str | None,
    issue_date: str | None,
    content_hash: str,
) -> str | None:
    """Return a conflict reason, or None if safe to import / already identical."""
    by_id = index["by_gmail_id"]
    existing = by_id.get(gmail_message_id)
    if existing:
        if existing.get("content_hash") == content_hash:
            return None
        return (
            "same_gmail_id_different_hash:"
            f"stored={existing.get('content_hash')} new={content_hash}"
        )

    if series_slug and issue_date:
        key = issue_key(series_slug, issue_date)
        other_id = index["by_issue_key"].get(key)
        if other_id and other_id != gmail_message_id:
            other = by_id.get(other_id) or {}
            if other.get("content_hash") == content_hash:
                return None
            return (
                f"issue_key_maps_to_other_message:{other_id}"
                f" key={key} folder={other.get('folder')}"
            )

    prior_id = index["by_content_hash"].get(content_hash)
    if prior_id and prior_id != gmail_message_id:
        return f"content_hash_already_archived_as:{prior_id}"

    return None


def is_exact_duplicate(
    index: dict[str, Any],
    *,
    gmail_message_id: str,
    content_hash: str,
) -> bool:
    existing = index["by_gmail_id"].get(gmail_message_id)
    if existing and existing.get("content_hash") == content_hash:
        return True
    return content_hash in index["by_content_hash"]


def record_import(
    index: dict[str, Any],
    *,
    gmail_message_id: str,
    series_slug: str,
    issue_date: str,
    content_hash: str,
    folder_name: str,
    drive_folder_id: str | None = None,
) -> None:
    entry = {
        "issue_date": issue_date,
        "series": series_slug,
        "folder": folder_name,
        "content_hash": content_hash,
        "drive_folder_id": drive_folder_id,
    }
    index["by_gmail_id"][gmail_message_id] = entry
    index["by_issue_key"][issue_key(series_slug, issue_date)] = gmail_message_id
    index["by_content_hash"][content_hash] = gmail_message_id
