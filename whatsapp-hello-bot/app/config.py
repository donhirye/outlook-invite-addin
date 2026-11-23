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


# Deployment mode. Anything other than the exact value "staging" means production,
# so an unset/misspelled value can never switch on staging-only features
# (Test Chat) or switch off production behavior.
APP_ENV = _env("APP_ENV", "production").lower()
IS_STAGING = APP_ENV == "staging"

_DEFAULT_ADMIN_PASSWORD = "changeme"
_DEFAULT_SECRET_KEY = "change-me-to-a-long-random-string"
ADMIN_PASSWORD = _env("ADMIN_PASSWORD", _DEFAULT_ADMIN_PASSWORD)
SECRET_KEY = _env("SECRET_KEY", _DEFAULT_SECRET_KEY)


def staging_config_problems() -> list[str]:
    """Reasons staging must refuse to start (empty list = fine / not staging)."""
    if not IS_STAGING:
        return []
    problems: list[str] = []
    if ADMIN_PASSWORD in {"", _DEFAULT_ADMIN_PASSWORD} or len(ADMIN_PASSWORD) < 12:
        problems.append("ADMIN_PASSWORD must be set to a unique value of 12+ characters")
    if SECRET_KEY in {"", _DEFAULT_SECRET_KEY} or len(SECRET_KEY) < 32:
        problems.append("SECRET_KEY must be set to a unique value of 32+ characters")
    if WHATSAPP_ACCESS_TOKEN:
        problems.append("WHATSAPP_ACCESS_TOKEN must not be set in staging")
    return problems

WHATSAPP_VERIFY_TOKEN = _env("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
WHATSAPP_ACCESS_TOKEN = _env("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = _env("WHATSAPP_PHONE_NUMBER_ID", "")
GRAPH_API_VERSION = _env("GRAPH_API_VERSION", "v21.0")

OPENAI_API_KEY = _env("OPENAI_API_KEY", "")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4o-mini")
# Eval framework (validation bake-offs only). See app/eval_framework/ and
# evals/framework/. When false, Engine 1 always uses Ep and ignores switching.
EVAL_FRAMEWORK_ENABLED = _env("EVAL_FRAMEWORK_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Which design when EVAL_FRAMEWORK_ENABLED: A | C | E | Ep
ANSWER_STRATEGY = _env("ANSWER_STRATEGY", "Ep")
# For gpt-5* reasoning models via Responses API. Empty = omit (non-reasoning models).
# minimal keeps FAQ quality high while cutting default medium-effort latency.
OPENAI_REASONING_EFFORT = _env("OPENAI_REASONING_EFFORT", "minimal").lower()
if OPENAI_REASONING_EFFORT not in {
    "",
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
}:
    OPENAI_REASONING_EFFORT = "minimal"

GREETING_FILE = BASE_DIR / "data" / "greeting.json"
FAQ_FILE = BASE_DIR / "data" / "science_olympiad_faq.txt"
METRICS_FILE = BASE_DIR / "data" / "usage_metrics.json"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Durable FAQ on Cloud Run (optional). When set, FAQ text + embedding index
# live in GCS so the admin FAQ UI shares one source of truth.
FAQ_GCS_BUCKET = _env("FAQ_GCS_BUCKET", "")
FAQ_GCS_OBJECT = _env("FAQ_GCS_OBJECT", "science_olympiad_faq.txt")
FAQ_GCS_INDEX_OBJECT = _env(
    "FAQ_GCS_INDEX_OBJECT",
    "science_olympiad_faq.txt.index.json",
)

# Combined newsletter FAQ + structured embedding index (eng-rag).
# Staging hierarchy mirrors local data/newsletter_archive/.
NEWSLETTER_COMBINED_FAQ_LOCAL = Path(
    _env(
        "NEWSLETTER_COMBINED_FAQ_LOCAL",
        str(BASE_DIR / "data" / "newsletter_archive" / "combined_FAQ_latest.csv"),
    )
)
NEWSLETTER_COMBINED_FAQ_GCS_OBJECT = _env(
    "NEWSLETTER_COMBINED_FAQ_GCS_OBJECT",
    "newsletter_archive/combined_FAQ_latest.csv",
)
NEWSLETTER_COMBINED_FAQ_INDEX_GCS_OBJECT = _env(
    "NEWSLETTER_COMBINED_FAQ_INDEX_GCS_OBJECT",
    "newsletter_archive/combined_FAQ_latest.csv.index.json",
)
# When true and FAQ_GCS_BUCKET is set, RAG loads the newsletter structured index.
USE_NEWSLETTER_COMBINED_FAQ_INDEX = _env(
    "USE_NEWSLETTER_COMBINED_FAQ_INDEX", "false"
).lower() in {"1", "true", "yes", "on"}

# RAG retrieval
FAQ_EMBEDDING_MODEL = _env("FAQ_EMBEDDING_MODEL", "text-embedding-3-small")
try:
    FAQ_TOP_K = max(1, int(_env("FAQ_TOP_K", "4")))
except ValueError:
    FAQ_TOP_K = 4

# If FAQ text is at or below this size, skip embeddings and send the whole FAQ
# to the LLM (faster for small school-event FAQs). Set 0 to always use RAG.
try:
    FAQ_SKIP_RAG_MAX_CHARS = max(0, int(_env("FAQ_SKIP_RAG_MAX_CHARS", "30000")))
except ValueError:
    FAQ_SKIP_RAG_MAX_CHARS = 30000

PARENT_FALLBACK_MESSAGE = (
    "Sorry, I'm having trouble answering right now. Please try again shortly."
)
FAQ_NOT_FOUND_MESSAGE = (
    "I couldn't find that information in the event FAQ. "
    "Please contact the PTSA Administrators."
)
# Parent-facing policy when someone asks for student PII (name/ID/phone/email).
STUDENT_PRIVACY_MESSAGE = (
    "Sorry — per PTSA privacy policy, a privacy filter has been applied. "
    "This assistant cannot provide student personal information "
    "(including student names, student IDs, phone numbers, or email addresses). "
    "Please contact the school office for help with student records."
)

# Guided conversations (Lost & Found, conferences, spiritwear, ...)
# Guided multi-step flows removed from the answer path; keep flag false.
GUIDED_ENABLED = _env("GUIDED_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def credential_status() -> dict[str, object]:
    return {
        "app_env": APP_ENV,
        "env_file": str(BASE_DIR / ".env"),
        "env_file_exists": (BASE_DIR / ".env").exists(),
        "access_token_len": len(WHATSAPP_ACCESS_TOKEN),
        "phone_number_id_set": bool(WHATSAPP_PHONE_NUMBER_ID),
        "phone_number_id": WHATSAPP_PHONE_NUMBER_ID,
        "verify_token_set": bool(WHATSAPP_VERIFY_TOKEN),
        "openai_api_key_set": bool(OPENAI_API_KEY),
        "openai_model": OPENAI_MODEL,
        "eval_framework_enabled": EVAL_FRAMEWORK_ENABLED,
        "answer_strategy": ANSWER_STRATEGY,
        "openai_reasoning_effort": OPENAI_REASONING_EFFORT or None,
        "faq_file_exists": FAQ_FILE.exists(),
        "faq_gcs_bucket": FAQ_GCS_BUCKET or None,
        "faq_embedding_model": FAQ_EMBEDDING_MODEL,
        "faq_top_k": FAQ_TOP_K,
        "faq_skip_rag_max_chars": FAQ_SKIP_RAG_MAX_CHARS,
    }
