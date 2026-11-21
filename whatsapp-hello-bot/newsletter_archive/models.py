"""Dataclasses for newsletter archive metadata and import outcomes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class DateBasis(str, Enum):
    PUBLICATION_STATED = "publication_stated"
    EMAIL_RECEIVED = "email_received"
    AMBIGUOUS = "ambiguous"


class ImportOutcome(str, Enum):
    IMPORTED = "imported"
    SKIPPED = "skipped"
    DUPLICATE = "duplicate"
    AMBIGUOUS_DATE = "ambiguous_date"
    CONFLICT = "conflict"
    FAILED = "failed"
    PREVIEW = "preview"


@dataclass
class IssueMetadata:
    gmail_message_id: str
    sender: str
    subject: str
    received_at: str  # ISO-8601 UTC
    stated_publication_date: str | None
    issue_date: str  # YYYY-MM-DD used for folder name
    date_basis: str
    smore_url: str | None
    source_content_hash: str
    newsletter_series: str | None = None  # e.g. Crones_Weekly_Newsletter
    folder_name: str | None = None  # full folder stem including date
    thread_id: str | None = None
    label_ids: list[str] = field(default_factory=list)
    gmail_query_used: str | None = None
    local_folder: str | None = None
    drive_folder_id: str | None = None
    eml_preserved: bool = False
    eml_limitation: str | None = None
    flags: list[str] = field(default_factory=list)
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IssueMetadata:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


@dataclass
class MessagePreview:
    gmail_message_id: str
    sender: str
    subject: str
    received_at: str
    issue_date: str | None
    date_basis: str
    content_hash: str
    smore_url: str | None
    suspected_duplicate: bool = False
    conflict_reason: str | None = None
    flags: list[str] = field(default_factory=list)


@dataclass
class ImportRecord:
    gmail_message_id: str
    outcome: ImportOutcome
    detail: str
    subject: str = ""
    issue_date: str | None = None
