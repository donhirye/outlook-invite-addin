"""Build one RAG chunk per structured FAQ row (no flat-text reparse)."""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.faq_records import ANSWERABLE_STATUSES, normalize_record

logger = logging.getLogger(__name__)

# GCS / relative provenance path when Source_URL is blank.
ISSUES_PREFIX = "newsletter_archive/issues"

_WEEKLY_ID_RE = re.compile(r"^WEEKLY-", re.I)
_PTSA_ID_RE = re.compile(r"^PTSA-", re.I)


@dataclass
class ChunkBuildReport:
    """Included chunks plus rows skipped by status rules."""

    included: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)

    @property
    def included_count(self) -> int:
        return len(self.included)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded)


def issue_folder_relpath(record: dict[str, Any]) -> str:
    """Local/GCS-relative issue folder for provenance (no trailing slash)."""
    faq_id = str(record.get("faq_id") or record.get("FAQ_ID") or "").strip()
    published = str(
        record.get("published_date") or record.get("Published_Date") or ""
    ).strip()
    source = str(record.get("source") or record.get("Source") or "").strip()

    if _WEEKLY_ID_RE.match(faq_id):
        series = "Crones_Weekly_Newsletter"
    elif _PTSA_ID_RE.match(faq_id):
        series = "Crone_PTSA_Newsletter"
    else:
        lower = source.lower()
        if "weekly" in lower:
            series = "Crones_Weekly_Newsletter"
        elif "ptsa" in lower:
            series = "Crone_PTSA_Newsletter"
        else:
            series = "Crone_Newsletter"

    if published:
        return f"{ISSUES_PREFIX}/{series}_{published}"
    return f"{ISSUES_PREFIX}/{series}"


def _source_url_or_issue_path(record: dict[str, Any]) -> str:
    """Preserve written URLs; blank / separator-only → issue folder path."""
    raw = str(record.get("source_url") or record.get("Source_URL") or "").strip()
    if not raw or raw in {";", ",", "|"}:
        return issue_folder_relpath(record)
    return raw


def embedding_text_for_record(record: dict[str, Any]) -> str:
    """Embeddable chunk body: category + Q + A only (no ## headings)."""
    category = str(record.get("category") or "").strip()
    question = str(record.get("question") or "").strip()
    answer = str(record.get("answer") or "").strip()
    return f"Category: {category}\nQ: {question}\nA: {answer}"


def chunk_dict_from_record(record: dict[str, Any], *, chunk_id: int) -> dict[str, Any]:
    """One index chunk: embedding text + structured metadata."""
    return {
        "id": chunk_id,
        "text": embedding_text_for_record(record),
        "metadata": {
            "faq_id": str(record.get("faq_id") or ""),
            "category": str(record.get("category") or ""),
            "source": str(record.get("source") or ""),
            "source_url": _source_url_or_issue_path(record),
            "published_date": str(record.get("published_date") or ""),
            "event_date": str(record.get("event_date") or ""),
            "status": str(record.get("status") or ""),
        },
    }


def _is_answerable(status: str) -> bool:
    return str(status or "").strip().lower() in ANSWERABLE_STATUSES


def chunk_faq_records(
    records: list[dict[str, Any]],
    *,
    answerable_only: bool = True,
) -> ChunkBuildReport:
    """Each eligible row → exactly one chunk from structured fields."""
    report = ChunkBuildReport()
    next_id = 0
    for raw in records:
        rec = normalize_record(raw)
        if rec is None:
            report.excluded.append(
                {
                    "faq_id": str(raw.get("faq_id") or raw.get("FAQ_ID") or ""),
                    "status": str(raw.get("status") or raw.get("Status") or ""),
                    "reason": "missing faq_id, question, or answer",
                }
            )
            continue

        status = str(rec.get("status") or "").strip()
        if answerable_only and not _is_answerable(status):
            report.excluded.append(
                {
                    "faq_id": str(rec.get("faq_id") or ""),
                    "status": status or "(empty)",
                    "reason": (
                        f"status {status or '(empty)'} not in "
                        f"{sorted(ANSWERABLE_STATUSES)}"
                    ),
                }
            )
            continue

        report.included.append(chunk_dict_from_record(rec, chunk_id=next_id))
        next_id += 1

    if report.excluded:
        logger.info(
            "FAQ structured chunk exclusions (%s): %s",
            report.excluded_count,
            "; ".join(
                f"{e['faq_id']} ({e['reason']})" for e in report.excluded[:20]
            ),
        )
    return report


def load_faq_csv_rows(path: Path | str) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8-sig")
    return load_faq_csv_text(text)


def load_faq_csv_text(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    for row in reader:
        rec = normalize_record(row or {})
        if rec:
            rows.append(rec)
    return rows


def chunk_faq_csv(
    path: Path | str,
    *,
    answerable_only: bool = True,
) -> ChunkBuildReport:
    return chunk_faq_records(
        load_faq_csv_rows(path),
        answerable_only=answerable_only,
    )
