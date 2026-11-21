"""Import report writer (IDs and outcomes only — no newsletter body)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from newsletter_archive.config import NEWSLETTER_REPORTS_DIR, ensure_local_dirs
from newsletter_archive.models import ImportOutcome, ImportRecord, MessagePreview


def write_import_report(
    *,
    gmail_query: str,
    dry_run: bool,
    records: list[ImportRecord],
    previews: list[MessagePreview] | None = None,
) -> Path:
    ensure_local_dirs()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = NEWSLETTER_REPORTS_DIR / f"import_report_{stamp}.json"

    counts: dict[str, int] = {o.value: 0 for o in ImportOutcome}
    for rec in records:
        counts[rec.outcome.value] = counts.get(rec.outcome.value, 0) + 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dry_run": dry_run,
        "gmail_query": gmail_query,
        "counts": counts,
        "records": [
            {
                "gmail_message_id": r.gmail_message_id,
                "outcome": r.outcome.value,
                "detail": r.detail,
                "subject": r.subject,
                "issue_date": r.issue_date,
            }
            for r in records
        ],
    }
    if previews is not None:
        payload["preview"] = [
            {
                "gmail_message_id": p.gmail_message_id,
                "sender": p.sender,
                "subject": p.subject,
                "received_at": p.received_at,
                "issue_date": p.issue_date,
                "date_basis": p.date_basis,
                "content_hash": p.content_hash,
                "suspected_duplicate": p.suspected_duplicate,
                "conflict_reason": p.conflict_reason,
                "flags": p.flags,
            }
            for p in previews
        ]

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def print_preview_table(previews: list[MessagePreview]) -> None:
    print(f"Matched messages: {len(previews)}")
    print("-" * 100)
    for p in previews:
        flags = ",".join(p.flags) if p.flags else ""
        dup = "DUP" if p.suspected_duplicate else ""
        conf = p.conflict_reason or ""
        print(
            f"{p.gmail_message_id}  {p.issue_date or '????-??-??'}  "
            f"{p.date_basis:20}  {dup:3}  {p.sender[:40]}"
        )
        print(f"  subject: {p.subject[:90]}")
        if conf:
            print(f"  conflict: {conf}")
        if flags:
            print(f"  flags: {flags}")
    print("-" * 100)
