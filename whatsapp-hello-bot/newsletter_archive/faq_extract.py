"""Heuristic (offline) FAQ CSV from archived newsletter HTML + metadata.

Prefer ``newsletter_archive.faq_llm`` for production-quality drafts. This module
remains as a no-API fallback (``--heuristic``).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass

from newsletter_archive.dates import parse_stated_date
from newsletter_archive.models import IssueMetadata
from newsletter_archive.privacy import scrub_or_flag
from newsletter_archive.sections import Section, html_to_sections
from newsletter_archive.text_clean import clean_faq_text

FAQ_COLUMNS = [
    "FAQ_ID",
    "Category",
    "Question",
    "Answer",
    "Source",
    "Source_URL",
    "Published_Date",
    "Event_Date",
    "Status",
]

_URL_RE = re.compile(r"https?://[^\s\]\)<>\"']+", re.I)
_WHEN_HINT = re.compile(
    r"\b(when|where|how|what time|deadline|register|signup|sign up|cost|fee|"
    r"volunteer|meeting|fundraiser|book fair|spirit|yearbook)\b",
    re.I,
)


@dataclass
class FaqRow:
    faq_id: str
    category: str
    question: str
    answer: str
    source: str
    source_url: str
    published_date: str
    event_date: str
    status: str

    def as_dict(self) -> dict[str, str]:
        return {
            "FAQ_ID": self.faq_id,
            "Category": self.category,
            "Question": self.question,
            "Answer": self.answer,
            "Source": self.source,
            "Source_URL": self.source_url,
            "Published_Date": self.published_date,
            "Event_Date": self.event_date,
            "Status": self.status,
        }


def _stable_faq_id(issue_date: str, category: str, question: str) -> str:
    digest = hashlib.sha1(
        f"{issue_date}|{category}|{question}".encode("utf-8")
    ).hexdigest()[:10]
    compact = issue_date.replace("-", "")
    return f"NL-{compact}-{digest}"


def _category_from_heading(heading: str) -> str:
    h = (heading or "").strip()
    if not h or h.lower() == "newsletter":
        return "PTSA Newsletter"
    return h[:80]


def _question_for_section(heading: str, body: str) -> str:
    heading = heading.strip() or "this newsletter item"
    if _WHEN_HINT.search(heading) or _WHEN_HINT.search(body[:200]):
        # Prefer natural parent questions
        lower = heading.lower()
        if lower.startswith(("when ", "where ", "how ", "what ")):
            return heading if heading.endswith("?") else f"{heading}?"
        return f"What should parents know about {heading}?"
    return f"What should parents know about {heading}?"


def _event_date_field(body: str, published: str) -> tuple[str, bool]:
    """Return (event_date_or_range, uncertain). Never invent years."""
    dates = parse_stated_date(body)
    if not dates:
        return "", False
    # If all dates are clearly before published issue and look historical, keep them
    # but do not rewrite as upcoming.
    unique = []
    for d in dates:
        if d not in unique:
            unique.append(d)
    if len(unique) == 1:
        return unique[0], False
    if len(unique) == 2:
        return f"{unique[0]} to {unique[1]}", False
    return ";".join(unique[:3]), True


def _urls_in(text: str) -> list[str]:
    return [m.group(0).rstrip(").,];") for m in _URL_RE.finditer(text or "")]


def sections_to_faq_rows(
    sections: list[Section],
    metadata: IssueMetadata,
) -> list[FaqRow]:
    source_name = f"Crone PTSA Newsletter – {metadata.issue_date}"
    source_url = metadata.smore_url or ""
    published = metadata.issue_date
    rows: list[FaqRow] = []
    seen_questions: set[str] = set()

    for sec in sections:
        body = clean_faq_text("\n".join(sec.body_lines))
        if len(body) < 40:
            continue
        body, pii = scrub_or_flag(body)
        body = clean_faq_text(body)
        category = clean_faq_text(_category_from_heading(sec.heading))
        question = clean_faq_text(_question_for_section(sec.heading, body))
        qkey = re.sub(r"\s+", " ", question.lower())
        if qkey in seen_questions:
            continue
        seen_questions.add(qkey)

        # Keep answer self-contained; include key URLs from the section.
        urls = _urls_in(body)
        answer = body
        # Cap extremely long answers for CSV readability
        if len(answer) > 1500:
            answer = answer[:1497].rstrip() + "..."
        if urls:
            # Ensure at least one URL remains if truncated oddly
            for u in urls[:3]:
                if u not in answer:
                    answer = f"{answer} {u}".strip()
        answer = clean_faq_text(answer)

        event_date, uncertain = _event_date_field(body, published)
        status = "Needs_Review" if (pii or uncertain) else "Active"
        if pii:
            # Do not ship student-PII-heavy shout-outs as Active FAQ drafts
            continue

        faq_id = _stable_faq_id(published, category, question)
        rows.append(
            FaqRow(
                faq_id=faq_id,
                category=category,
                question=question,
                answer=answer,
                source=clean_faq_text(source_name),
                source_url=source_url,
                published_date=published,
                event_date=event_date,
                status=status,
            )
        )
    return rows


def generate_faq_csv(html: str, metadata: IssueMetadata) -> str:
    rows = sections_to_faq_rows(html_to_sections(html), metadata)
    buf = io.StringIO()
    buf.write("\ufeff")  # UTF-8 BOM for Excel on Windows
    writer = csv.DictWriter(buf, fieldnames=FAQ_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row.as_dict())
    return buf.getvalue()
