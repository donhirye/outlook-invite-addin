"""Gmail → immutable local archive (+ optional Drive upload on --confirm)."""

from __future__ import annotations

import logging
from pathlib import Path

from newsletter_archive.archive_io import ArchiveConflictError, write_source_archive
from newsletter_archive.auth import get_credentials
from newsletter_archive.config import (
    NEWSLETTER_DEFAULT_GMAIL_QUERY,
    artifact_name,
    ensure_local_dirs,
    issue_basename,
)
from newsletter_archive.naming import series_slug_from_subject
from newsletter_archive.drive_api import (
    DriveConfigError,
    build_drive_service,
    ensure_issue_folder,
    require_parent_folder_id,
    upload_file,
)
from newsletter_archive.gmail_api import (
    build_gmail_service,
    build_search_query,
    fetch_message_bundle,
    list_message_ids,
    to_preview,
)
from newsletter_archive.index_store import (
    is_exact_duplicate,
    load_index,
    lookup_conflicts,
    record_import,
    save_index,
)
from newsletter_archive.models import ImportOutcome, ImportRecord, IssueMetadata
from newsletter_archive.report import print_preview_table, write_import_report

logger = logging.getLogger(__name__)


def run_ingest(
    *,
    query: str | None = None,
    label: str | None = None,
    dry_run: bool = True,
    confirm: bool = False,
    max_results: int = 500,
    drive_parent_folder_id: str | None = None,
    write_local_only: bool = False,
) -> Path:
    """Run ingestion. Default is dry-run (no writes).

    Drive writes require ``confirm=True``. Local archive is also written only
    when ``confirm=True`` (or ``write_local_only=True`` for offline fixtures).
    """
    ensure_local_dirs()
    if confirm and dry_run:
        # confirm implies a real write; dry_run wins if both somehow set
        raise ValueError("Pass either --dry-run or --confirm, not both.")

    effective_query = query or (None if label else NEWSLETTER_DEFAULT_GMAIL_QUERY or None)
    gmail_query = build_search_query(query=effective_query, label=label)

    logger.info("Newsletter ingest starting dry_run=%s confirm=%s", dry_run, confirm)
    creds = get_credentials()
    gmail = build_gmail_service(creds)
    message_ids = list_message_ids(gmail, gmail_query, max_results=max_results)
    index = load_index()

    previews = []
    records: list[ImportRecord] = []
    bundles: list[dict] = []

    for mid in message_ids:
        try:
            bundle = fetch_message_bundle(gmail, mid)
        except Exception as exc:
            logger.exception("Failed fetching gmail_id=%s", mid)
            records.append(
                ImportRecord(
                    gmail_message_id=mid,
                    outcome=ImportOutcome.FAILED,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        dup = is_exact_duplicate(
            index,
            gmail_message_id=bundle["gmail_message_id"],
            content_hash=bundle["content_hash"],
        )
        conflict = None
        if not dup:
            conflict = lookup_conflicts(
                index,
                gmail_message_id=bundle["gmail_message_id"],
                series_slug=series_slug_from_subject(bundle.get("subject") or ""),
                issue_date=bundle["issue_date"],
                content_hash=bundle["content_hash"],
            )
        preview = to_preview(bundle, suspected_duplicate=dup, conflict=conflict)
        previews.append(preview)
        bundles.append({**bundle, "_dup": dup, "_conflict": conflict})

    print_preview_table(previews)

    if dry_run or (not confirm and not write_local_only):
        for b in bundles:
            mid = b["gmail_message_id"]
            if b["_dup"]:
                outcome, detail = ImportOutcome.DUPLICATE, "exact_duplicate"
            elif b["date_basis"] == "ambiguous" or not b["issue_date"]:
                outcome, detail = ImportOutcome.AMBIGUOUS_DATE, "ambiguous_or_missing_date"
            elif b["_conflict"]:
                outcome, detail = ImportOutcome.CONFLICT, b["_conflict"]
            else:
                outcome, detail = ImportOutcome.PREVIEW, "would_import"
            records.append(
                ImportRecord(
                    gmail_message_id=mid,
                    outcome=outcome,
                    detail=detail,
                    subject=b.get("subject") or "",
                    issue_date=b.get("issue_date"),
                )
            )
        report = write_import_report(
            gmail_query=gmail_query,
            dry_run=True,
            records=records,
            previews=previews,
        )
        print(f"Dry-run report: {report}")
        print("No files written. Re-run with --confirm to write local archive + Drive.")
        return report

    # Confirmed write path
    drive = None
    parent_id = None
    if confirm and not write_local_only:
        parent_id = require_parent_folder_id(drive_parent_folder_id)
        drive = build_drive_service(creds)

    for b in bundles:
        mid = b["gmail_message_id"]
        subject = b.get("subject") or ""
        try:
            if b["_dup"]:
                records.append(
                    ImportRecord(
                        gmail_message_id=mid,
                        outcome=ImportOutcome.DUPLICATE,
                        detail="exact_duplicate",
                        subject=subject,
                        issue_date=b.get("issue_date"),
                    )
                )
                continue
            if b["date_basis"] == "ambiguous" or not b["issue_date"]:
                records.append(
                    ImportRecord(
                        gmail_message_id=mid,
                        outcome=ImportOutcome.AMBIGUOUS_DATE,
                        detail="flagged_for_review_no_write",
                        subject=subject,
                        issue_date=None,
                    )
                )
                continue
            if b["_conflict"]:
                records.append(
                    ImportRecord(
                        gmail_message_id=mid,
                        outcome=ImportOutcome.CONFLICT,
                        detail=b["_conflict"],
                        subject=subject,
                        issue_date=b.get("issue_date"),
                    )
                )
                continue

            issue_date = b["issue_date"]
            series = series_slug_from_subject(subject)
            folder_name = issue_basename(subject, issue_date)
            meta = IssueMetadata(
                gmail_message_id=mid,
                sender=b["sender"],
                subject=subject,
                received_at=b["received_at"],
                stated_publication_date=(
                    issue_date if b["date_basis"] == "publication_stated" else None
                ),
                issue_date=issue_date,
                date_basis=b["date_basis"],
                smore_url=b.get("smore_url"),
                source_content_hash=b["content_hash"],
                newsletter_series=series,
                folder_name=folder_name,
                thread_id=b.get("thread_id"),
                label_ids=list(b.get("label_ids") or []),
                gmail_query_used=gmail_query,
                eml_preserved=bool(b.get("eml_bytes")),
                eml_limitation=b.get("eml_limitation"),
                flags=list(b.get("flags") or []),
            )

            folder = write_source_archive(
                subject=subject,
                issue_date=issue_date,
                metadata=meta,
                html=b["html"],
                eml_bytes=b.get("eml_bytes"),
            )

            drive_folder_id = None
            if drive is not None and parent_id is not None:
                drive_folder_id = ensure_issue_folder(drive, parent_id, folder_name)
                # Upload source artifacts only (generators are separate).
                for kind in ("html", "metadata", "eml"):
                    name = artifact_name(subject, issue_date, kind)
                    local = folder / name
                    if not local.exists():
                        missing = folder / f"{folder_name}_Source.eml.MISSING.txt"
                        if kind == "eml" and missing.exists():
                            upload_file(drive, drive_folder_id, missing, overwrite=False)
                        continue
                    try:
                        upload_file(drive, drive_folder_id, local, overwrite=False)
                    except FileExistsError:
                        logger.info(
                            "Drive file exists, leaving untouched: %s (gmail_id=%s)",
                            name,
                            mid,
                        )
                meta.drive_folder_id = drive_folder_id
                # Refresh metadata with drive folder id
                write_source_archive(
                    subject=subject,
                    issue_date=issue_date,
                    metadata=meta,
                    html=b["html"],
                    eml_bytes=b.get("eml_bytes"),
                )
                # Re-upload metadata after drive id stamped
                upload_file(
                    drive,
                    drive_folder_id,
                    folder / artifact_name(subject, issue_date, "metadata"),
                    overwrite=True,
                )

            record_import(
                index,
                gmail_message_id=mid,
                series_slug=series,
                issue_date=issue_date,
                content_hash=b["content_hash"],
                folder_name=folder_name,
                drive_folder_id=drive_folder_id,
            )
            save_index(index)
            records.append(
                ImportRecord(
                    gmail_message_id=mid,
                    outcome=ImportOutcome.IMPORTED,
                    detail=f"local={folder.name}",
                    subject=subject,
                    issue_date=issue_date,
                )
            )
        except (ArchiveConflictError, DriveConfigError, FileExistsError) as exc:
            records.append(
                ImportRecord(
                    gmail_message_id=mid,
                    outcome=ImportOutcome.CONFLICT,
                    detail=str(exc),
                    subject=subject,
                    issue_date=b.get("issue_date"),
                )
            )
        except Exception as exc:
            logger.exception("Import failed gmail_id=%s", mid)
            records.append(
                ImportRecord(
                    gmail_message_id=mid,
                    outcome=ImportOutcome.FAILED,
                    detail=f"{type(exc).__name__}: {exc}",
                    subject=subject,
                    issue_date=b.get("issue_date"),
                )
            )

    report = write_import_report(
        gmail_query=gmail_query,
        dry_run=False,
        records=records,
        previews=previews,
    )
    print(f"Import report: {report}")
    return report
