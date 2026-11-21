"""Generate a human-review PDF from archived newsletter content."""

from __future__ import annotations

import re
from pathlib import Path

from newsletter_archive.models import IssueMetadata
from newsletter_archive.sections import generate_cleaned_sections_markdown, html_to_sections


def _require_reportlab():
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            XPreformatted,
        )
    except ImportError as exc:
        raise RuntimeError(
            "reportlab is required. pip install -r requirements-newsletter.txt"
        ) from exc
    return (
        letter,
        ParagraphStyle,
        getSampleStyleSheet,
        inch,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        XPreformatted,
    )


_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_MD_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")


def _escape_xml(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _md_inline_to_para(text: str) -> str:
    """Convert simple markdown links to reportlab link tags."""

    def repl(match: re.Match[str]) -> str:
        label = _escape_xml(match.group(1))
        url = match.group(2).replace('"', "%22")
        return f'<link href="{url}" color="blue"><u>{label}</u></link>'

    return _LINK_RE.sub(repl, _escape_xml(text))


def build_review_pdf(
    *,
    html: str,
    metadata: IssueMetadata,
    output_path: Path,
    prefer_cleaned_markdown: str | None = None,
) -> Path:
    (
        letter,
        ParagraphStyle,
        getSampleStyleSheet,
        inch,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        XPreformatted,
    ) = _require_reportlab()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReviewTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=8,
    )
    h_style = ParagraphStyle(
        "ReviewH",
        parent=styles["Heading2"],
        fontSize=12,
        spaceBefore=10,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "ReviewBody",
        parent=styles["BodyText"],
        fontSize=9,
        leading=12,
        spaceAfter=4,
    )
    banner_style = ParagraphStyle(
        "ReviewBanner",
        parent=styles["BodyText"],
        fontSize=10,
        textColor="#833",
        spaceAfter=12,
    )

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=f"REVIEW: Crone PTSA Newsletter {metadata.issue_date}",
    )

    story = []
    story.append(
        Paragraph(
            "REVIEW / ARCHIVE COPY — not primary RAG input; not published to the chatbot.",
            banner_style,
        )
    )
    story.append(
        Paragraph(
            _escape_xml(metadata.subject or f"Crone PTSA Newsletter {metadata.issue_date}"),
            title_style,
        )
    )
    meta_bits = [
        f"Issue date: {metadata.issue_date} (basis: {metadata.date_basis})",
        f"Received: {metadata.received_at}",
        f"From: {metadata.sender}",
        f"Gmail id: {metadata.gmail_message_id}",
        f"Content hash: {metadata.source_content_hash}",
    ]
    if metadata.smore_url:
        meta_bits.append(
            f'Smore (reference): <link href="{metadata.smore_url}" color="blue">'
            f"<u>{_escape_xml(metadata.smore_url)}</u></link>"
        )
    for bit in meta_bits:
        story.append(Paragraph(bit if bit.startswith("Smore") else _escape_xml(bit), body_style))
    story.append(Spacer(1, 0.2 * inch))

    if prefer_cleaned_markdown:
        md = prefer_cleaned_markdown
    else:
        md = generate_cleaned_sections_markdown(html, metadata)

    for line in md.splitlines():
        if not line.strip():
            story.append(Spacer(1, 0.08 * inch))
            continue
        hm = _MD_HEADING.match(line)
        if hm:
            story.append(Paragraph(_escape_xml(hm.group(2)), h_style))
            continue
        if line.startswith(">"):
            story.append(Paragraph(_escape_xml(line.lstrip("> ").strip()), banner_style))
            continue
        if line.startswith("- "):
            story.append(Paragraph("• " + _md_inline_to_para(line[2:]), body_style))
            continue
        story.append(Paragraph(_md_inline_to_para(line), body_style))

    # Ensure we actually used archived content path (sections derived from HTML)
    _ = html_to_sections(html)

    doc.build(story)
    return output_path
