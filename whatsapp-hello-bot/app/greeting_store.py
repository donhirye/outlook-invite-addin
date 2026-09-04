import json
from pathlib import Path

from app.config import GREETING_FILE

DEFAULT_MESSAGE = "hello, how are you"


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
