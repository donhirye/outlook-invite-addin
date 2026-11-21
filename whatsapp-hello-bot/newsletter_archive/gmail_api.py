"""Gmail API helpers (read-only). Never reconstruct issues from Smore URLs."""

from __future__ import annotations

import logging
from typing import Any

from newsletter_archive.html_extract import (
    b64url_decode,
    extract_bodies_from_eml,
    extract_bodies_from_gmail_payload,
    find_smore_url,
    header_value,
    parse_raw_eml,
)
from newsletter_archive.hashing import content_hash
from newsletter_archive.dates import (
    received_iso_from_date_header,
    received_iso_from_internal_ms,
    resolve_issue_date,
)
from newsletter_archive.models import DateBasis, MessagePreview

logger = logging.getLogger(__name__)


def build_gmail_service(credentials: Any) -> Any:
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "google-api-python-client is required. "
            "pip install -r requirements-newsletter.txt"
        ) from exc
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def build_search_query(*, query: str | None, label: str | None) -> str:
    parts: list[str] = []
    if query:
        parts.append(query.strip())
    if label:
        # Gmail search operator for a user label name.
        lab = label.strip()
        if not lab.lower().startswith("label:"):
            lab = f"label:{lab}"
        parts.append(lab)
    combined = " ".join(parts).strip()
    if not combined:
        raise ValueError(
            "Provide --query and/or --label (or set NEWSLETTER_DEFAULT_GMAIL_QUERY)."
        )
    return combined


def list_message_ids(service: Any, gmail_query: str, *, max_results: int = 500) -> list[str]:
    ids: list[str] = []
    page_token = None
    while True:
        kwargs: dict[str, Any] = {
            "userId": "me",
            "q": gmail_query,
            "maxResults": min(100, max_results - len(ids)),
        }
        if page_token:
            kwargs["pageToken"] = page_token
        resp = service.users().messages().list(**kwargs).execute()
        for item in resp.get("messages") or []:
            mid = item.get("id")
            if mid:
                ids.append(mid)
            if len(ids) >= max_results:
                return ids
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    logger.info("Gmail list matched %s message id(s) for query (id-only logged)", len(ids))
    return ids


def fetch_message_bundle(service: Any, message_id: str) -> dict[str, Any]:
    """Fetch raw RFC822 (for .eml) plus full payload (structured MIME)."""
    raw_resp = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="raw")
        .execute()
    )
    full_resp = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )

    eml_bytes: bytes | None = None
    eml_limitation: str | None = None
    raw_b64 = raw_resp.get("raw")
    if raw_b64:
        try:
            eml_bytes = b64url_decode(raw_b64)
        except Exception as exc:
            eml_limitation = f"raw_decode_failed:{type(exc).__name__}"
    else:
        eml_limitation = "gmail_raw_missing"

    payload = full_resp.get("payload") or {}
    html, plain = extract_bodies_from_gmail_payload(payload)
    if eml_bytes and (not html or not plain):
        try:
            msg = parse_raw_eml(eml_bytes)
            html2, plain2 = extract_bodies_from_eml(msg)
            html = html or html2
            plain = plain or plain2
        except Exception as exc:
            if not eml_limitation:
                eml_limitation = f"eml_parse_partial:{type(exc).__name__}"

    headers = payload.get("headers") or []
    subject = header_value(headers, "Subject")
    sender = header_value(headers, "From")
    date_hdr = header_value(headers, "Date")
    internal = full_resp.get("internalDate") or raw_resp.get("internalDate") or "0"
    received = received_iso_from_date_header(date_hdr) or received_iso_from_internal_ms(
        internal
    )

    smore = find_smore_url(html, plain, subject)
    issue_date, basis, flags = resolve_issue_date(
        subject=subject,
        body_text=plain or html,
        received_at_iso=received,
    )
    chash = content_hash(html)

    return {
        "gmail_message_id": message_id,
        "thread_id": full_resp.get("threadId"),
        "label_ids": list(full_resp.get("labelIds") or []),
        "sender": sender,
        "subject": subject,
        "received_at": received,
        "html": html,
        "plain": plain,
        "eml_bytes": eml_bytes,
        "eml_limitation": eml_limitation,
        "smore_url": smore,
        "issue_date": issue_date,
        "date_basis": basis.value if isinstance(basis, DateBasis) else str(basis),
        "flags": flags,
        "content_hash": chash,
    }


def to_preview(bundle: dict[str, Any], *, suspected_duplicate: bool, conflict: str | None) -> MessagePreview:
    return MessagePreview(
        gmail_message_id=bundle["gmail_message_id"],
        sender=bundle["sender"],
        subject=bundle["subject"],
        received_at=bundle["received_at"],
        issue_date=bundle["issue_date"],
        date_basis=bundle["date_basis"],
        content_hash=bundle["content_hash"],
        smore_url=bundle["smore_url"],
        suspected_duplicate=suspected_duplicate,
        conflict_reason=conflict,
        flags=list(bundle.get("flags") or []),
    )
