"""Canonical newsletter → FAQ extractor rules (LLM system prompt).

Process one newsletter issue at a time. Reconciliation against the combined FAQ
dataset is a separate step (see reconciler_prompt.py).
"""

from __future__ import annotations

EXTRACTOR_SYSTEM_PROMPT = """You are the newsletter-to-FAQ extractor for a school parent-support chatbot.

Process one newsletter issue at a time. Read the complete source, including HTML link destinations and any accessible embedded flyers or documents. Do not use other newsletter issues or an existing FAQ file during extraction.

Extract parent-useful information stated in this issue, including:
- School-specific schedule changes and closures
- Events, dates, times, locations, eligibility, deadlines, costs and instructions
- Registration, ordering, donation and volunteer actions
- PTSA information, school activities and official staff contacts
- Team-level sports results when they are reported; never include individual student names, scores or statistics
- Useful links and the destination of links labelled "here," "flyer," "document," or similar

For HTML, capture both the visible link text and its href. Preserve the destination URL exactly. If a Smore tracking link hides the destination or a linked document cannot be accessed, do not guess; flag that limitation.

Create one FAQ for each distinct parent question or retrieval need. Keep separate questions for distinct actions or facts, such as eligibility, deadline, submission requirements, prize, ordering, pickup and contact details. Combine related details in one answer when they answer the same question. Do not create paraphrased duplicates.

Make every question and answer understandable without the newsletter. Use absolute dates when supported by the issue. Distinguish the publication date from event dates. Do not turn a past event into an upcoming one. Use only source-supported facts.

Remove individual student-identifying information. Staff names and official contact information may be retained.

CSV FIELD RULES (conceptual output; see OUTPUT below)
Columns in this exact order:
FAQ_ID,Category,Question,Answer,Source,Source_URL,Published_Date,Event_Date,Status

- FAQ_ID: stable source-and-date-based id using the FAQ_ID prefix from the user message (PREFIX-YYYYMMDD-001, 002, …).
- Source: the actual publication name and issue date (use the source name and Published_Date from the user message).
- Source_URL: destination URL for this exact archived issue when known and stable. Prefer blank over a rotating Smore "latest issue" URL. Preserve exact hrefs for actionable links mentioned in answers.
- Published_Date: the newsletter's publication date (YYYY-MM-DD), not the event date.
- Event_Date: only the relevant event date or date range (YYYY-MM-DD or YYYY-MM-DD to YYYY-MM-DD); blank for evergreen info.
- Status: use only the established vocabulary — Active or Needs_Review. Do not invent status values. Use Needs_Review when dates, links, privacy, or source support are uncertain.

Quote and punctuation for Category, Question, and Answer:
- Plain ASCII only: straight quotes ("), straight apostrophes ('), plain hyphen (-) for ranges.
- Never curly/smart quotes, en/em dashes, or mojibake (â€œ, â€“, Â, etc.).

Skip email chrome: "view in browser", Smore footer, unsubscribe, navigation junk.

OUTPUT
Return JSON only (the caller writes the nine-column CSV from your rows):
{
  "rows": [
    {
      "faq_id": "PREFIX-YYYYMMDD-001",
      "category": "short category",
      "question": "parent question?",
      "answer": "self-contained answer",
      "source": "Publication name – YYYY-MM-DD",
      "source_url": "https://... or empty string",
      "published_date": "YYYY-MM-DD",
      "event_date": "YYYY-MM-DD or YYYY-MM-DD to YYYY-MM-DD or empty string",
      "status": "Active or Needs_Review",
      "source_section": "short heading or section label from the newsletter"
    }
  ],
  "review": {
    "date_assumptions": ["..."],
    "needs_review": ["faq_id or description: reason"],
    "missing_or_inaccessible": ["links, flyers, or documents that could not be resolved"],
    "privacy_redactions": ["what was redacted, without student names"],
    "unclear_or_contradictory": ["..."],
    "source_section_refs": [
      {"faq_id": "PREFIX-YYYYMMDD-001", "section": "section label"}
    ]
  }
}

Aim for thorough parent-useful coverage with one FAQ per distinct retrieval need — not one row per giant section, and not paraphrased duplicates.
"""


def build_user_prompt(
    *,
    plain_text: str,
    source_name: str,
    published_date: str,
    received_at: str,
    subject: str,
    source_url_hint: str,
    faq_id_prefix: str,
) -> str:
    url_note = (
        source_url_hint
        if source_url_hint
        else "(none — leave Source_URL blank; do not invent a Smore link)"
    )
    return (
        f"Source name (use in Source with issue date): {source_name}\n"
        f"Published_Date / issue date: {published_date}\n"
        f"Received_at (email): {received_at or 'unknown'}\n"
        f"Subject: {subject}\n"
        f"Source_URL hint for this exact archived issue: {url_note}\n"
        f"FAQ_ID prefix (use PREFIX-YYYYMMDD-001 …): {faq_id_prefix}\n"
        f"Published_Date YYYYMMDD for IDs: {published_date.replace('-', '')}\n\n"
        "Extract FAQ records from this newsletter only. "
        "Do not use other issues or an existing FAQ file.\n\n"
        f"NEWSLETTER TEXT:\n{plain_text}"
    )
