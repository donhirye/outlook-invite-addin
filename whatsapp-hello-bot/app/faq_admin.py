import logging
import re
from pathlib import Path

from app.config import FAQ_ADMIN_PHONES
from app.faq_rag import rebuild_index
from app.faq_store import get_faq_text, set_faq_text

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "*Event FAQ Assistant*\n\n"
    "Send any question about the event and I’ll answer from the FAQ.\n\n"
    "*Examples*\n"
    "• Where should I park?\n"
    "• What time should students arrive?\n\n"
    "Organizers can add FAQ entries with /faq (admin only)."
)

FAQ_USAGE_TEXT = (
    "*Add to FAQ* (admins only)\n\n"
    "Send:\n"
    "```\n"
    "/faq\n"
    "Q: Can grandparents attend?\n"
    "A: Yes. Please sign in at the gym entrance.\n"
    "```\n\n"
    "Or one line:\n"
    "/faq Q: ... A: ..."
)


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D+", "", phone or "")


def is_faq_admin(phone: str) -> bool:
    if not FAQ_ADMIN_PHONES:
        return False
    normalized = normalize_phone(phone)
    return normalized in FAQ_ADMIN_PHONES


def is_help_command(text: str) -> bool:
    cleaned = (text or "").strip().lower()
    return cleaned in {"help", "/help", "menu", "/menu", "start"}


def is_faq_command(text: str) -> bool:
    cleaned = (text or "").strip()
    return cleaned.lower().startswith("/faq")


def parse_faq_command(text: str) -> tuple[str, str] | None:
    """Parse /faq command into (question, answer)."""
    cleaned = (text or "").strip()
    if not cleaned.lower().startswith("/faq"):
        return None

    body = cleaned[4:].strip()
    # Allow optional colon after /faq
    if body.startswith(":"):
        body = body[1:].strip()

    if not body:
        return None

    match = re.search(
        r"q\s*:\s*(.+?)\s*a\s*:\s*(.+)\s*$",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None

    question = " ".join(match.group(1).split()).strip()
    answer = " ".join(match.group(2).split()).strip()
    if not question or not answer:
        return None
    return question, answer


def append_faq_entry(
    question: str,
    answer: str,
    *,
    faq_path: Path | None = None,
) -> str:
    """Append a Q&A to durable FAQ storage and rebuild the embedding index."""
    block = f"Q: {question}\nA: {answer}"
    try:
        existing = get_faq_text(faq_path=faq_path).rstrip()
        new_text = f"{existing}\n\n{block}"
    except (FileNotFoundError, ValueError):
        new_text = block

    set_faq_text(new_text, faq_path=faq_path)
    try:
        rebuild_index(new_text, faq_path=faq_path)
    except Exception:
        logger.exception("FAQ saved but embedding index rebuild failed")

    logger.info("Appended FAQ entry via durable store")
    return (
        "*Saved to FAQ*\n\n"
        f"*Q:* {question}\n"
        f"*A:* {answer}"
    )


def format_parent_answer(answer: str) -> str:
    cleaned = (answer or "").strip()
    if not cleaned:
        return cleaned
    # Keep refusal/fallback messages plain; dress up normal answers lightly.
    if cleaned.startswith("I couldn't find") or cleaned.startswith("Sorry,"):
        return cleaned
    return f"*FAQ answer*\n{cleaned}"
