import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Dangerous vars that must not leak into DEV from the parent shell / leftover env.
_DEV_CLEAR_VARS = (
    "FAQ_GCS_BUCKET",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "OPENAI_API_KEY",
    "ADMIN_PASSWORD",
    "SECRET_KEY",
)


def _load_dotenv_files() -> Path | None:
    """Load env files. DEV never silently inherits ``.env`` (prod/staging secrets).

    Precedence:
    1. ``DOTENV_PATH`` (absolute or relative to BASE_DIR) — used by ``run-dev.ps1``
    2. If process ``APP_ENV=development`` already set → only ``.env.development``
    3. Otherwise ``.env`` (local prod-like / legacy)
    """
    explicit = (os.environ.get("DOTENV_PATH") or "").strip()
    app_env_hint = (os.environ.get("APP_ENV") or "").strip().lower()

    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = BASE_DIR / path
        # Scrub inherited cloud/WhatsApp/OpenAI secrets before loading DEV file.
        if app_env_hint == "development" or "development" in path.name:
            for name in _DEV_CLEAR_VARS:
                os.environ.pop(name, None)
        load_dotenv(path, encoding="utf-8-sig", override=True)
        return path

    if app_env_hint == "development":
        for name in _DEV_CLEAR_VARS:
            os.environ.pop(name, None)
        path = BASE_DIR / ".env.development"
        load_dotenv(path, encoding="utf-8-sig", override=True)
        return path

    path = BASE_DIR / ".env"
    load_dotenv(path, encoding="utf-8-sig")
    return path if path.exists() else None


_LOADED_DOTENV = _load_dotenv_files()


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    if value is None:
        return default
    cleaned = value.strip().strip('"').strip("'")
    return cleaned


# Deployment mode. Only exact values enable non-production features.
# Unset / misspelled / anything else => production behavior (fail closed for Test Chat).
APP_ENV = _env("APP_ENV", "production").lower()
IS_STAGING = APP_ENV == "staging"
IS_DEVELOPMENT = APP_ENV == "development"
IS_NON_PRODUCTION = IS_STAGING or IS_DEVELOPMENT

_DEFAULT_ADMIN_PASSWORD = "changeme"
_DEFAULT_SECRET_KEY = "change-me-to-a-long-random-string"
ADMIN_PASSWORD = _env("ADMIN_PASSWORD", _DEFAULT_ADMIN_PASSWORD)
SECRET_KEY = _env("SECRET_KEY", _DEFAULT_SECRET_KEY)

WHATSAPP_VERIFY_TOKEN = _env("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
WHATSAPP_ACCESS_TOKEN = _env("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = _env("WHATSAPP_PHONE_NUMBER_ID", "")
GRAPH_API_VERSION = _env("GRAPH_API_VERSION", "v21.0")

OPENAI_API_KEY = _env("OPENAI_API_KEY", "")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4o-mini")
# For gpt-5* reasoning models via Responses API. Empty = omit (non-reasoning models).
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

# Comma-separated admin phones allowed to run /faq (digits with country code, no +)
_raw_admin_phones = _env("FAQ_ADMIN_PHONES", "")
FAQ_ADMIN_PHONES = {
    "".join(ch for ch in part if ch.isdigit())
    for part in _raw_admin_phones.split(",")
    if part.strip()
}

# Mutable runtime data: isolated under data/dev when APP_ENV=development.
SHARED_DATA_DIR = BASE_DIR / "data"
DATA_DIR = SHARED_DATA_DIR / "dev" if IS_DEVELOPMENT else SHARED_DATA_DIR

GREETING_FILE = DATA_DIR / "greeting.json"
FAQ_FILE = DATA_DIR / "science_olympiad_faq.txt"
METRICS_FILE = DATA_DIR / "usage_metrics.json"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Durable FAQ on Cloud Run (optional). Forbidden in local development.
# FAQ_GCS_PREFIX isolates experiment deploys (e.g. experiments/feature-foo/) so
# baseline bucket object names are never overwritten.
FAQ_GCS_BUCKET = _env("FAQ_GCS_BUCKET", "")
_FAQ_GCS_PREFIX = _env("FAQ_GCS_PREFIX", "").strip().strip("/")


def _faq_gcs_path(name: str) -> str:
    """Join FAQ_GCS_PREFIX to a basename; leave absolute-ish object paths alone."""
    name = (name or "").lstrip("/")
    if not _FAQ_GCS_PREFIX:
        return name
    if name.startswith(f"{_FAQ_GCS_PREFIX}/"):
        return name
    # Already a nested object path set explicitly — do not double-prefix.
    if "/" in name:
        return name
    return f"{_FAQ_GCS_PREFIX}/{name}"


FAQ_GCS_PREFIX = _FAQ_GCS_PREFIX
FAQ_GCS_OBJECT = _faq_gcs_path(_env("FAQ_GCS_OBJECT", "science_olympiad_faq.txt"))
FAQ_GCS_INDEX_OBJECT = _faq_gcs_path(
    _env(
        "FAQ_GCS_INDEX_OBJECT",
        "science_olympiad_faq.txt.index.json",
    )
)
# Branch that produced this Cloud Run revision (experiment tracking).
DEPLOY_BRANCH = _env("DEPLOY_BRANCH", "")

# RAG retrieval (match production defaults for DEV baseline)
FAQ_EMBEDDING_MODEL = _env("FAQ_EMBEDDING_MODEL", "text-embedding-3-small")
try:
    FAQ_TOP_K = max(1, int(_env("FAQ_TOP_K", "4")))
except ValueError:
    FAQ_TOP_K = 4

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
STUDENT_PRIVACY_MESSAGE = (
    "Sorry — per PTSA privacy policy, a privacy filter has been applied. "
    "This assistant cannot provide student personal information "
    "(including student names, student IDs, phone numbers, or email addresses). "
    "Please contact the school office for help with student records."
)

GUIDED_ENABLED = _env("GUIDED_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Deployed commit label (Cloud Run / local). Public via /health; never a secret.
GIT_SHA = _env("GIT_SHA", "") or _env("K_REVISION", "")

# Read-only Releases dashboard probes. Staging uses GitHub API (token in Secret Manager).
STAGING_BASE_URL = _env("STAGING_BASE_URL", "").rstrip("/")
PRODUCTION_BASE_URL = _env("PRODUCTION_BASE_URL", "").rstrip("/")
# Fine-grained PAT: contents + metadata (+ pull requests) read-only. Never write.
GITHUB_TOKEN = _env("GITHUB_TOKEN", "") or _env("GH_TOKEN", "")
GITHUB_REPO = _env("GITHUB_REPO", "donhirye/outlook-invite-addin")  # owner/repo

# Read-only Cloud Run describe targets (staging-runtime needs roles/run.viewer).
CLOUD_RUN_REGION = _env("CLOUD_RUN_REGION", "us-central1")
STAGING_CLOUD_RUN_PROJECT = _env("STAGING_CLOUD_RUN_PROJECT", "vi1234-staging")
STAGING_CLOUD_RUN_SERVICE = _env("STAGING_CLOUD_RUN_SERVICE", "whatsapp-faq-bot-staging")
PRODUCTION_CLOUD_RUN_PROJECT = _env("PRODUCTION_CLOUD_RUN_PROJECT", "vi1234")
PRODUCTION_CLOUD_RUN_SERVICE = _env("PRODUCTION_CLOUD_RUN_SERVICE", "whatsapp-faq-bot")


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


def development_config_problems() -> list[str]:
    """Reasons local DEV must refuse to start (empty list = fine / not development)."""
    if not IS_DEVELOPMENT:
        return []
    problems: list[str] = []
    if FAQ_GCS_BUCKET:
        problems.append(
            "FAQ_GCS_BUCKET must be empty in development "
            "(local DEV cannot use staging/production GCS)"
        )
    if not (BASE_DIR / ".env.development").exists() and not (
        os.environ.get("DOTENV_PATH") or ""
    ).strip():
        problems.append(
            "Create whatsapp-hello-bot/.env.development "
            "(copy from .env.development.example)"
        )
    return problems


def env_config_problems() -> list[str]:
    return staging_config_problems() + development_config_problems()


def credential_status() -> dict[str, object]:
    return {
        "app_env": APP_ENV,
        "data_dir": str(DATA_DIR),
        "env_file": str(_LOADED_DOTENV) if _LOADED_DOTENV else None,
        "env_file_exists": bool(_LOADED_DOTENV and Path(_LOADED_DOTENV).exists()),
        "access_token_len": len(WHATSAPP_ACCESS_TOKEN),
        "phone_number_id_set": bool(WHATSAPP_PHONE_NUMBER_ID),
        "phone_number_id": WHATSAPP_PHONE_NUMBER_ID,
        "verify_token_set": bool(WHATSAPP_VERIFY_TOKEN),
        "openai_api_key_set": bool(OPENAI_API_KEY),
        "openai_model": OPENAI_MODEL,
        "openai_reasoning_effort": OPENAI_REASONING_EFFORT or None,
        "faq_file_exists": FAQ_FILE.exists(),
        "faq_admin_count": len(FAQ_ADMIN_PHONES),
        "faq_gcs_bucket": FAQ_GCS_BUCKET or None,
        "faq_embedding_model": FAQ_EMBEDDING_MODEL,
        "faq_top_k": FAQ_TOP_K,
        "faq_skip_rag_max_chars": FAQ_SKIP_RAG_MAX_CHARS,
    }
