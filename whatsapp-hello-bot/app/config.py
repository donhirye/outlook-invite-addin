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

GREETING_FILE = BASE_DIR / "data" / "greeting.json"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def credential_status() -> dict[str, object]:
    return {
        "env_file": str(BASE_DIR / ".env"),
        "env_file_exists": (BASE_DIR / ".env").exists(),
        "access_token_len": len(WHATSAPP_ACCESS_TOKEN),
        "phone_number_id_set": bool(WHATSAPP_PHONE_NUMBER_ID),
        "phone_number_id": WHATSAPP_PHONE_NUMBER_ID,
        "verify_token_set": bool(WHATSAPP_VERIFY_TOKEN),
    }
