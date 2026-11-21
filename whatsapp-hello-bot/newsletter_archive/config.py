"""Configuration for newsletter archive (env + paths). Credentials never logged."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PACKAGE_DIR = Path(__file__).resolve().parent
BOT_ROOT = _PACKAGE_DIR.parent
REPO_ROOT = BOT_ROOT.parent

# Load bot .env if present (same convention as the WhatsApp app). Does not override
# already-set process env vars.
load_dotenv(BOT_ROOT / ".env", override=False)

# Google OAuth client secrets JSON (Desktop app). Never commit this file.
GOOGLE_OAUTH_CLIENT_SECRETS = os.getenv(
    "GOOGLE_OAUTH_CLIENT_SECRETS",
    str(BOT_ROOT / ".secrets" / "google_oauth_client.json"),
)
GOOGLE_OAUTH_TOKEN_PATH = os.getenv(
    "GOOGLE_OAUTH_TOKEN_PATH",
    str(BOT_ROOT / ".secrets" / "google_newsletter_token.json"),
)

# Parent Drive folder for per-issue folders. Configure via env — do not scatter IDs.
NEWSLETTER_DRIVE_PARENT_FOLDER_ID = (
    os.getenv("NEWSLETTER_DRIVE_PARENT_FOLDER_ID", "").strip()
)

# Local mirror of archived issues (generators read from here / any issue folder).
NEWSLETTER_LOCAL_ROOT = Path(
    os.getenv(
        "NEWSLETTER_LOCAL_ROOT",
        str(BOT_ROOT / "data" / "newsletter_archive"),
    )
).resolve()

NEWSLETTER_ISSUES_DIR = NEWSLETTER_LOCAL_ROOT / "issues"
NEWSLETTER_INDEX_PATH = NEWSLETTER_LOCAL_ROOT / "index.json"
NEWSLETTER_REPORTS_DIR = NEWSLETTER_LOCAL_ROOT / "reports"

# Default Gmail search when neither --query nor --label is given (empty = require flag).
NEWSLETTER_DEFAULT_GMAIL_QUERY = os.getenv("NEWSLETTER_DEFAULT_GMAIL_QUERY", "").strip()

# Minimum OAuth scopes. drive.file creates/manages files this app creates; gmail is read-only.
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
OAUTH_SCOPES = (GMAIL_READONLY_SCOPE, DRIVE_FILE_SCOPE)

FILE_SUFFIXES = {
    "eml": "_Source.eml",
    "html": "_Source.html",
    "metadata": "_Metadata.json",
    "sections": "_Cleaned_Sections.md",
    "faq": "_FAQ.csv",
    "faq_review": "_FAQ_Review.md",
    "pdf": "_Review.pdf",
}


def issue_basename(subject: str, issue_date: str) -> str:
    """Return ``<SeriesFromSubject>_YYYY-MM-DD`` (Weekly vs PTSA differ)."""
    from newsletter_archive.naming import issue_basename as _basename

    return _basename(subject, issue_date)


def artifact_name(subject: str, issue_date: str, kind: str) -> str:
    suffix = FILE_SUFFIXES[kind]
    return f"{issue_basename(subject, issue_date)}{suffix}"


def ensure_local_dirs() -> None:
    NEWSLETTER_ISSUES_DIR.mkdir(parents=True, exist_ok=True)
    NEWSLETTER_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (BOT_ROOT / ".secrets").mkdir(parents=True, exist_ok=True)
