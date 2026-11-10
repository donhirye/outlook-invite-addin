import logging
import re
from pathlib import Path

from app.config import FAQ_ADMIN_PHONES
from app.faq_rag import rebuild_index
from app.faq_store import get_faq_text, set_faq_text

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "*PTSA Event Chatbot*\n\n"
    "Hi! I'm the PTSA chatbot for this school event.\n\n"
    "My answers are based only on information provided by the PTSA organizers. "
    "If I don't know something, please ask an admin/organizer directly in your group chat.\n\n"
    "*Examples*\n"
    "• Where is Lost & Found?\n"
    "• My child lost a jacket\n"
    "• How do I schedule a conference?\n\n"
    "During a guided chat, send cancel to stop.\n"
    "Organizers can add FAQ entries with /faq (admin only)."
)

FAQ_USAGE_TEXT = (
    "*Add to FAQ* (admins only)\n\n"
    "Send:\n"
    "```\n"
    "/faq\n"
    "Q: Can grandparents attend?\n"
    "A: Yes. Please sign in at the gym entrance.\n"
    "Source: Crone PTSA Newsletter – Nov 2026\n"
    "```\n\n"
    "Or one line:\n"
    "/faq Q: ... A: ... Source: ..."
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


def is_opener_message(text: str) -> bool:
    """True for greetings / prefilled wa.me openers, not real FAQ questions."""
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return True
    if cleaned in {
        "hi",
        "hello",
        "hey",
        "hola",
        "yo",
        "start",
        "/start",
        "good morning",
        "good afternoon",
        "good evening",
    }:
        return True
    # Typical wa.me ?text= openers like:
    # "Hi, I have a question about Kendall 5th Grade Celebration"
    opener_patterns = (
        r"^(hi|hello|hey)[,!]?\s+i have a question about\b",
        r"^i have a question about\b",
        r"^question about\b",
        r"^ask(ing)? about\b",
    )
    return any(re.search(pattern, cleaned) for pattern in opener_patterns)


def is_faq_command(text: str) -> bool:
    cleaned = (text or "").strip()
    return cleaned.lower().startswith("/faq")


def parse_faq_command(text: str) -> tuple[str, str, str | None] | None:
    """Parse /faq command into (question, answer, optional source)."""
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
        r"q\s*:\s*(.+?)\s*a\s*:\s*(.+?)(?:\s*source\s*:\s*(.+))?\s*$",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None

    question = " ".join(match.group(1).split()).strip()
    answer = " ".join(match.group(2).split()).strip()
    source_raw = match.group(3)
    source = " ".join((source_raw or "").split()).strip() or None
    if not question or not answer:
        return None
    return question, answer, source


def append_faq_entry(
    question: str,
    answer: str,
    source: str | None = None,
    *,
    faq_path: Path | None = None,
) -> str:
    """Append a Q&A (optional Source) to durable FAQ storage and rebuild index."""
    block = f"Q: {question}\nA: {answer}"
    source_clean = " ".join((source or "").split()).strip()
    if source_clean:
        block = f"{block}\nSource: {source_clean}"
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
    saved = (
        "*Saved to FAQ*\n\n"
        f"*Q:* {question}\n"
        f"*A:* {answer}"
    )
    if source_clean:
        saved = f"{saved}\n*Source:* {source_clean}"
    return saved


SOURCE_PLACEHOLDER = "Source: Google Docs"
_STRIP_SOURCE_RE = re.compile(r"(?im)^\s*source\s*:.*$")


def strip_source_lines(answer: str) -> str:
    """Remove any Source: lines the model (or paste) may have invented."""
    without = _STRIP_SOURCE_RE.sub("", answer or "")
    return re.sub(r"\n{3,}", "\n\n", without).strip()


def format_parent_answer(
    answer: str,
    *,
    source_name: str | None = None,
    source_url: str | None = None,
) -> str:
    cleaned = strip_source_lines(answer)
    if not cleaned:
        return cleaned
    # Keep refusal/fallback messages plain; dress up normal answers lightly.
    if cleaned.startswith("I couldn't find") or cleaned.startswith("Sorry,"):
        return cleaned
    name = (source_name or "").strip() or "Crone PTSA FAQ"
    url = (source_url or "").strip()
    if url:
        source_line = f"Source: {name}\n{url}"
    else:
        source_line = f"Source: {name}"
    return f"*FAQ answer*\n{cleaned}\n\n{source_line}"
