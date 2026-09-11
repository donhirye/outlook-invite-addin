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
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4o-mini")

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

# Durable FAQ on Cloud Run (optional). When set, FAQ text + embedding index
# live in GCS so admin UI and WhatsApp /faq share one source of truth.
FAQ_GCS_BUCKET = _env("FAQ_GCS_BUCKET", "")
FAQ_GCS_OBJECT = _env("FAQ_GCS_OBJECT", "science_olympiad_faq.txt")
FAQ_GCS_INDEX_OBJECT = _env(
    "FAQ_GCS_INDEX_OBJECT",
    "science_olympiad_faq.txt.index.json",
)

# RAG retrieval
FAQ_EMBEDDING_MODEL = _env("FAQ_EMBEDDING_MODEL", "text-embedding-3-small")
try:
    FAQ_TOP_K = max(1, int(_env("FAQ_TOP_K", "4")))
except ValueError:
    FAQ_TOP_K = 4

# If FAQ text is at or below this size, skip embeddings and send the whole FAQ
# to the LLM (faster for small school-event FAQs). Set 0 to always use RAG.
try:
    FAQ_SKIP_RAG_MAX_CHARS = max(0, int(_env("FAQ_SKIP_RAG_MAX_CHARS", "12000")))
except ValueError:
    FAQ_SKIP_RAG_MAX_CHARS = 12000

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
        "faq_gcs_bucket": FAQ_GCS_BUCKET or None,
        "faq_embedding_model": FAQ_EMBEDDING_MODEL,
        "faq_top_k": FAQ_TOP_K,
        "faq_skip_rag_max_chars": FAQ_SKIP_RAG_MAX_CHARS,
    }
