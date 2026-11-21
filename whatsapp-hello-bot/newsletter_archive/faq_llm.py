"""LLM-based FAQ extraction using the canonical extractor rules."""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from newsletter_archive.extractor_prompt import (
    EXTRACTOR_SYSTEM_PROMPT,
    build_user_prompt,
)
from newsletter_archive.faq_extract import FAQ_COLUMNS, FaqRow
from newsletter_archive.models import IssueMetadata
from newsletter_archive.text_clean import clean_faq_text

logger = logging.getLogger(__name__)

_SMORE_LIVE = re.compile(r"app\.smore\.com/n/", re.I)


@dataclass
class ReviewReport:
    date_assumptions: list[str] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)
    missing_or_inaccessible: list[str] = field(default_factory=list)
    privacy_redactions: list[str] = field(default_factory=list)
    unclear_or_contradictory: list[str] = field(default_factory=list)
    source_section_refs: list[dict[str, str]] = field(default_factory=list)
    model: str = ""
    issue_folder: str = ""
    row_count: int = 0

    def to_markdown(self) -> str:
        lines = [
            "# FAQ extraction review report",
            "",
            f"- Issue folder: `{self.issue_folder}`",
            f"- Model: `{self.model}`",
            f"- Candidate rows: {self.row_count}",
            "",
            "## Date assumptions and ambiguous dates",
            *_bullets(self.date_assumptions),
            "",
            "## Records that need human review",
            *_bullets(self.needs_review),
            "",
            "## Missing or inaccessible links, flyers, or images",
            *_bullets(self.missing_or_inaccessible),
            "",
            "## Student privacy redactions",
            *_bullets(self.privacy_redactions),
            "",
            "## Unclear or contradictory source text",
            *_bullets(self.unclear_or_contradictory),
            "",
            "## Source-section references (audit)",
        ]
        if self.source_section_refs:
            for ref in self.source_section_refs:
                fid = ref.get("faq_id") or ""
                sec = ref.get("section") or ""
                lines.append(f"- `{fid}` ← {sec}")
        else:
            lines.append("- (none)")
        lines.append("")
        return "\n".join(lines)


@dataclass
class ExtractionResult:
    rows: list[FaqRow]
    review: ReviewReport
    csv_text: str
    review_markdown: str


def _bullets(items: list[str]) -> list[str]:
    if not items:
        return ["- (none)"]
    return [f"- {item}" for item in items]


def newsletter_plain_text(html: str) -> str:
    from bs4 import BeautifulSoup

    try:
        soup = BeautifulSoup(html or "", "lxml")
    except Exception:
        soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = text.replace("\u200c", "").replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?:\u00ad|\u200b|\u200c|\s){8,}", " ", text)
    return text.strip()


def source_display_name(metadata: IssueMetadata) -> str:
    series = (metadata.newsletter_series or "").lower()
    subject = (metadata.subject or "").lower()
    if "weekly" in series or "weekly" in subject:
        return "Crone's Weekly Newsletter"
    if "ptsa" in series or "ptsa" in subject:
        return "Crone PTSA Newsletter"
    return "Crone Newsletter"


def faq_id_prefix(metadata: IssueMetadata) -> str:
    series = (metadata.newsletter_series or "").lower()
    subject = (metadata.subject or "").lower()
    ymd = (metadata.issue_date or "unknown").replace("-", "")
    if "weekly" in series or "weekly" in subject:
        kind = "WEEKLY"
    elif "ptsa" in series or "ptsa" in subject:
        kind = "PTSA"
    else:
        kind = "NL"
    return f"{kind}-{ymd}"


def resolve_source_url(metadata: IssueMetadata) -> str:
    """Blank for rotating Smore newsletter links; keep only if non-Smore or known-stable."""
    url = (metadata.smore_url or "").strip()
    if not url:
        return ""
    if _SMORE_LIVE.search(url):
        # Live Smore issue URLs often rotate to the latest edition — not archival.
        return ""
    return url


def _normalize_rows(
    raw_rows: list[dict],
    *,
    metadata: IssueMetadata,
    source_name: str,
    source_url: str,
    id_prefix: str,
) -> list[FaqRow]:
    published = metadata.issue_date
    rows: list[FaqRow] = []
    seen_q: set[str] = set()
    for i, raw in enumerate(raw_rows, start=1):
        if not isinstance(raw, dict):
            continue
        question = clean_faq_text(raw.get("question") or "")
        answer = clean_faq_text(raw.get("answer") or "")
        if not question or not answer:
            continue
        qkey = re.sub(r"\s+", " ", question.lower())
        if qkey in seen_q:
            continue
        seen_q.add(qkey)

        status = (raw.get("status") or "Active").strip() or "Active"
        if status not in {"Active", "Needs_Review"}:
            status = "Needs_Review"

        faq_id = (raw.get("faq_id") or "").strip()
        if not faq_id:
            faq_id = f"{id_prefix}-{i:03d}"
        # Keep stable sequential IDs under our prefix when model drifts.
        if not faq_id.upper().startswith(id_prefix.upper()):
            faq_id = f"{id_prefix}-{i:03d}"

        row_source = clean_faq_text(raw.get("source") or "") or clean_faq_text(source_name)
        row_url = (raw.get("source_url") or "").strip() or source_url
        row_published = (raw.get("published_date") or "").strip() or published
        rows.append(
            FaqRow(
                faq_id=faq_id,
                category=clean_faq_text(raw.get("category") or "General") or "General",
                question=question,
                answer=answer,
                source=row_source,
                source_url=row_url,
                published_date=row_published,
                event_date=(raw.get("event_date") or "").strip(),
                status=status,
            )
        )
    # Re-number sequentially for stability
    renumbered: list[FaqRow] = []
    for i, row in enumerate(rows, start=1):
        renumbered.append(
            FaqRow(
                faq_id=f"{id_prefix}-{i:03d}",
                category=row.category,
                question=row.question,
                answer=row.answer,
                source=row.source,
                source_url=row.source_url,
                published_date=row.published_date,
                event_date=row.event_date,
                status=row.status,
            )
        )
    return renumbered


def _parse_review(data: dict, *, model: str, issue_folder: str, row_count: int) -> ReviewReport:
    rev = data.get("review") or {}
    if not isinstance(rev, dict):
        rev = {}

    def _str_list(key: str) -> list[str]:
        val = rev.get(key) or []
        if not isinstance(val, list):
            return []
        return [str(x).strip() for x in val if str(x).strip()]

    refs_raw = rev.get("source_section_refs") or []
    refs: list[dict[str, str]] = []
    if isinstance(refs_raw, list):
        for item in refs_raw:
            if isinstance(item, dict):
                refs.append(
                    {
                        "faq_id": str(item.get("faq_id") or "").strip(),
                        "section": str(item.get("section") or "").strip(),
                    }
                )

    # Also pull per-row source_section into refs if missing
    rows = data.get("rows") or []
    if isinstance(rows, list) and not refs:
        for i, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            sec = (row.get("source_section") or "").strip()
            if sec:
                refs.append(
                    {
                        "faq_id": str(row.get("faq_id") or f"row-{i}").strip(),
                        "section": sec,
                    }
                )

    return ReviewReport(
        date_assumptions=_str_list("date_assumptions"),
        needs_review=_str_list("needs_review"),
        missing_or_inaccessible=_str_list("missing_or_inaccessible"),
        privacy_redactions=_str_list("privacy_redactions"),
        unclear_or_contradictory=_str_list("unclear_or_contradictory"),
        source_section_refs=refs,
        model=model,
        issue_folder=issue_folder,
        row_count=row_count,
    )


def rows_to_csv(rows: list[FaqRow]) -> str:
    # UTF-8 BOM so Excel on Windows opens the file without â€œ / â€“ mojibake.
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.DictWriter(buf, fieldnames=FAQ_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row.as_dict())
    return buf.getvalue()


def extract_faqs_llm(
    html: str,
    metadata: IssueMetadata,
    *,
    model: str | None = None,
    max_chars: int = 28000,
    issue_folder: str | Path | None = None,
) -> ExtractionResult:
    """Call OpenAI with the canonical extractor prompt; return CSV rows + review."""
    from openai import OpenAI

    from app.config import OPENAI_API_KEY, OPENAI_MODEL

    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is required for LLM FAQ extraction. "
            "Pass --heuristic to use the offline section-based extractor."
        )

    plain = clean_faq_text(newsletter_plain_text(html))
    if len(plain) > max_chars:
        plain = plain[:max_chars] + "\n\n[TRUNCATED FOR MODEL CONTEXT]"

    source_name = source_display_name(metadata)
    source_url = resolve_source_url(metadata)
    id_prefix = faq_id_prefix(metadata)
    use_model = (model or OPENAI_MODEL or "gpt-4o-mini").strip()

    user = build_user_prompt(
        plain_text=plain,
        source_name=source_name,
        published_date=metadata.issue_date,
        received_at=metadata.received_at or "",
        subject=metadata.subject or "",
        source_url_hint=source_url,
        faq_id_prefix=id_prefix,
    )

    client = OpenAI(api_key=OPENAI_API_KEY)
    # Some models (e.g. gpt-5.6-luna) reject temperature=0; omit by default.
    kwargs = {
        "model": use_model,
        "messages": [
            {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    resp = client.chat.completions.create(**kwargs)

    raw = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Model returned non-JSON: {raw[:400]}") from exc

    raw_rows = data.get("rows") or data.get("faqs") or []
    if not isinstance(raw_rows, list) or not raw_rows:
        raise RuntimeError(f"No FAQ rows in model response: {raw[:500]}")

    rows = _normalize_rows(
        raw_rows,
        metadata=metadata,
        source_name=source_name,
        source_url=source_url,
        id_prefix=id_prefix,
    )
    folder_label = str(issue_folder or metadata.folder_name or metadata.issue_date)
    review = _parse_review(
        data,
        model=use_model,
        issue_folder=folder_label,
        row_count=len(rows),
    )
    # Align source_section_refs faq_ids to renumbered IDs when possible
    if review.source_section_refs and len(review.source_section_refs) == len(rows):
        for i, row in enumerate(rows):
            review.source_section_refs[i]["faq_id"] = row.faq_id

    csv_text = rows_to_csv(rows)
    md = review.to_markdown()
    usage = getattr(resp, "usage", None)
    if usage:
        logger.info(
            "FAQ LLM usage prompt=%s completion=%s rows=%s",
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
            len(rows),
        )
    return ExtractionResult(
        rows=rows,
        review=review,
        csv_text=csv_text,
        review_markdown=md,
    )
