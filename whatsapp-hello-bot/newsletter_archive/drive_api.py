"""Google Drive helpers for per-issue archive folders.

Does not change sharing permissions. Does not make files public.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any

from newsletter_archive.config import NEWSLETTER_DRIVE_PARENT_FOLDER_ID

logger = logging.getLogger(__name__)


class DriveConfigError(RuntimeError):
    pass


def build_drive_service(credentials: Any) -> Any:
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise RuntimeError(
            "google-api-python-client is required. "
            "pip install -r requirements-newsletter.txt"
        ) from exc
    # MediaFileUpload imported for side-effect availability check in callers
    _ = MediaFileUpload
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def require_parent_folder_id(folder_id: str | None = None) -> str:
    fid = (folder_id or NEWSLETTER_DRIVE_PARENT_FOLDER_ID or "").strip()
    if not fid:
        raise DriveConfigError(
            "NEWSLETTER_DRIVE_PARENT_FOLDER_ID is not set.\n"
            "Add it to whatsapp-hello-bot/.env (folder ID only, not the full URL).\n"
            "See docs/newsletter-archive.md."
        )
    return fid


def find_child_folder(service: Any, parent_id: str, name: str) -> str | None:
    safe = name.replace("'", "\\'")
    q = (
        f"name = '{safe}' and '{parent_id}' in parents and "
        "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    resp = (
        service.files()
        .list(q=q, spaces="drive", fields="files(id, name)", pageSize=10)
        .execute()
    )
    files = resp.get("files") or []
    if not files:
        return None
    if len(files) > 1:
        logger.warning(
            "Multiple Drive folders named %s under parent; using first id=%s",
            name,
            files[0]["id"],
        )
    return files[0]["id"]


def ensure_issue_folder(service: Any, parent_id: str, folder_name: str) -> str:
    name = folder_name
    existing = find_child_folder(service, parent_id, name)
    if existing:
        return existing
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    created = service.files().create(body=meta, fields="id, name").execute()
    logger.info("Created Drive issue folder name=%s id=%s", name, created["id"])
    return created["id"]


def find_file_in_folder(service: Any, folder_id: str, name: str) -> str | None:
    safe = name.replace("'", "\\'")
    q = f"name = '{safe}' and '{folder_id}' in parents and trashed = false"
    resp = (
        service.files()
        .list(q=q, spaces="drive", fields="files(id, name)", pageSize=5)
        .execute()
    )
    files = resp.get("files") or []
    return files[0]["id"] if files else None


def upload_file(
    service: Any,
    folder_id: str,
    local_path: Path,
    *,
    overwrite: bool = False,
) -> str:
    from googleapiclient.http import MediaFileUpload

    name = local_path.name
    mime, _ = mimetypes.guess_type(name)
    mime = mime or "application/octet-stream"
    existing = find_file_in_folder(service, folder_id, name)
    media = MediaFileUpload(str(local_path), mimetype=mime, resumable=True)
    if existing:
        if not overwrite:
            raise FileExistsError(
                f"Drive file already exists in folder (id={existing}): {name}"
            )
        updated = (
            service.files()
            .update(fileId=existing, media_body=media, fields="id")
            .execute()
        )
        return updated["id"]
    created = (
        service.files()
        .create(
            body={"name": name, "parents": [folder_id]},
            media_body=media,
            fields="id",
        )
        .execute()
    )
    return created["id"]
