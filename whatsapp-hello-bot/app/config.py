import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# utf-8-sig strips Windows Notepad BOM that can break variable names
load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig")


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    if value is None:
        return default
    cleaned = value.strip().strip('"').strip("'")
    return cleaned


ADMIN_PASSWORD = _env("ADMIN_PASSWORD", "changeme")
SECRET_KEY = _env("SECRET_KEY", "change-me-to-a-long-random-string")

WHATSAPP_VERIFY_TOKEN = _env("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
WHATSAPP_ACCESS_TOKEN = _env("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = _env("WHATSAPP_PHONE_NUMBER_ID", "")
GRAPH_API_VERSION = _env("GRAPH_API_VERSION", "v21.0")

OPENAI_API_KEY = _env("OPENAI_API_KEY", "")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-5.6-luna")

# Comma-separated WhatsApp numbers allowed to run /faq (digits with country code, no +)
# Example: 18122165774,15551234567
_raw_admin_phones = _env("FAQ_ADMIN_PHONES", "")
FAQ_ADMIN_PHONES = {
    "".join(ch for ch in part if ch.isdigit())
    for part in _raw_admin_phones.split(",")
    if part.strip()
}

GREETING_FILE = BASE_DIR / "data" / "greeting.json"
FAQ_FILE = BASE_DIR / "data" / "science_olympiad_faq.txt"
METRICS_FILE = BASE_DIR / "data" / "usage_metrics.json"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

PARENT_FALLBACK_MESSAGE = (
    "Sorry, I'm having trouble answering right now. Please try again shortly."
)
FAQ_NOT_FOUND_MESSAGE = (
    "I couldn't find that information in the event FAQ. "
    "Please contact the event organizer."
)


def credential_status() -> dict[str, object]:
    return {
        "env_file": str(BASE_DIR / ".env"),
        "env_file_exists": (BASE_DIR / ".env").exists(),
        "access_token_len": len(WHATSAPP_ACCESS_TOKEN),
        "phone_number_id_set": bool(WHATSAPP_PHONE_NUMBER_ID),
        "phone_number_id": WHATSAPP_PHONE_NUMBER_ID,
        "verify_token_set": bool(WHATSAPP_VERIFY_TOKEN),
        "openai_api_key_set": bool(OPENAI_API_KEY),
        "openai_model": OPENAI_MODEL,
        "faq_file_exists": FAQ_FILE.exists(),
        "faq_admin_count": len(FAQ_ADMIN_PHONES),
    }
