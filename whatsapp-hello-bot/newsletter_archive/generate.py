"""Independent artifact generators (read archive only; no Gmail/Smore fetch)."""

from __future__ import annotations

import logging
from pathlib import Path

from newsletter_archive.archive_io import load_metadata, load_source_html, resolve_issue_dir
from newsletter_archive.config import artifact_name
from newsletter_archive.faq_extract import generate_faq_csv
from newsletter_archive.pdf_review import build_review_pdf
from newsletter_archive.sections import generate_cleaned_sections_markdown

logger = logging.getLogger(__name__)


def _artifact(metadata, kind: str) -> str:
    subject = metadata.subject or metadata.folder_name or "Crone_Newsletter"
    return artifact_name(subject, metadata.issue_date, kind)


def generate_sections(issue_folder: str | Path) -> Path:
    issue_dir = resolve_issue_dir(issue_folder)
    metadata = load_metadata(issue_dir)
    html = load_source_html(issue_dir)
    md = generate_cleaned_sections_markdown(html, metadata)
    out = issue_dir / _artifact(metadata, "sections")
    if out.exists():
        logger.info("Overwriting generator artifact only: %s", out.name)
    out.write_text(md, encoding="utf-8", newline="\n")
    logger.info("Wrote cleaned sections: %s", out)
    return out


def generate_faq(
    issue_folder: str | Path,
    *,
    heuristic: bool = False,
    model: str | None = None,
) -> tuple[Path, Path | None]:
    """Write FAQ.csv (and FAQ_Review.md for LLM mode). Returns (csv_path, review_path)."""
    issue_dir = resolve_issue_dir(issue_folder)
    metadata = load_metadata(issue_dir)
    html = load_source_html(issue_dir)
    csv_out = issue_dir / _artifact(metadata, "faq")
    review_out = issue_dir / _artifact(metadata, "faq_review")

    if heuristic:
        csv_text = generate_faq_csv(html, metadata)
        csv_out.write_text(csv_text, encoding="utf-8", newline="\n")
        logger.info("Wrote heuristic FAQ CSV: %s", csv_out)
        return csv_out, None

    from newsletter_archive.faq_llm import extract_faqs_llm

    result = extract_faqs_llm(
        html,
        metadata,
        model=model,
        issue_folder=issue_dir.name,
    )
    csv_out.write_text(result.csv_text, encoding="utf-8", newline="\n")
    review_out.write_text(result.review_markdown, encoding="utf-8", newline="\n")
    logger.info(
        "Wrote LLM FAQ CSV (%s rows): %s ; review: %s",
        len(result.rows),
        csv_out,
        review_out,
    )
    return csv_out, review_out


def generate_pdf(issue_folder: str | Path) -> Path:
    issue_dir = resolve_issue_dir(issue_folder)
    metadata = load_metadata(issue_dir)
    html = load_source_html(issue_dir)
    sections_path = issue_dir / _artifact(metadata, "sections")
    cleaned = None
    if sections_path.exists():
        cleaned = sections_path.read_text(encoding="utf-8")
    out = issue_dir / _artifact(metadata, "pdf")
    build_review_pdf(
        html=html,
        metadata=metadata,
        output_path=out,
        prefer_cleaned_markdown=cleaned,
    )
    logger.info("Wrote review PDF: %s", out)
    return out
