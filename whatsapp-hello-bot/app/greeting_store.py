import json
from pathlib import Path

from app.config import GREETING_FILE

DEFAULT_MESSAGE = (
    "Hi! I'm the PTSA chatbot for this school event.\n\n"
    "My answers are based only on information provided by the PTSA organizers. "
    "If I don't know something, please ask an admin/organizer directly in your group chat.\n\n"
    "Send me your question anytime — for example: Where should I park?"
)


def get_greeting() -> str:
    path = Path(GREETING_FILE)
    if not path.exists():
        return DEFAULT_MESSAGE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        message = (data.get("message") or "").strip()
        return message or DEFAULT_MESSAGE
    except (json.JSONDecodeError, OSError):
        return DEFAULT_MESSAGE


def set_greeting(message: str) -> str:
    cleaned = (message or "").strip() or DEFAULT_MESSAGE
    path = Path(GREETING_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"message": cleaned}, indent=2) + "\n",
        encoding="utf-8",
    )
    return cleaned
