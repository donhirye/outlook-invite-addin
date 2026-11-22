import re

HELP_TEXT = (
    "*PTSA Event Chatbot*\n\n"
    "Hi! I'm the PTSA chatbot for this school event.\n\n"
    "My answers are based only on information provided by the PTSA organizers. "
    "If I don't know something, please ask an admin/organizer directly in your group chat.\n\n"
    "*Examples*\n"
    "• Where is Lost & Found?\n"
    "• My child lost a jacket\n"
    "• How do I schedule a conference?"
)


def is_help_command(text: str) -> bool:
    cleaned = (text or "").strip().lower()
    return cleaned in {"help", "/help", "menu", "/menu", "start"}


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
