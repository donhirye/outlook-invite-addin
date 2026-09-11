"""Store the WhatsApp group launch link settings (bot number + prefill text).

This is separate from the FAQ answers. The prefill/subject is what parents see
in the wa.me ?text= draft when they tap the group link.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import quote

from app.config import BASE_DIR, FAQ_GCS_BUCKET, FAQ_GCS_OBJECT

logger = logging.getLogger(__name__)

EVENT_LINK_FILE = BASE_DIR / "data" / "event_link.json"
EVENT_LINK_GCS_OBJECT = "event_link.json"

DEFAULT_PREFILL = "Hi, I have a question about Kendall 5th Grade Celebration"
DEFAULT_BOT_PHONE = ""


def _gcs_enabled() -> bool:
    return bool(FAQ_GCS_BUCKET)


def _normalize_phone(phone: str) -> str:
    return re.sub(r"\D+", "", phone or "")


def _default_settings() -> dict[str, str]:
    return {
        "bot_phone": DEFAULT_BOT_PHONE,
        "prefill_text": DEFAULT_PREFILL,
    }


def _read_local() -> dict[str, str]:
    path = Path(EVENT_LINK_FILE)
    if not path.exists():
        return _default_settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed reading %s", path)
        return _default_settings()
    phone = data.get("bot_phone") or data.get("phone") or ""
    prefill = data.get("prefill_text") or data.get("subject") or ""
    return {
        "bot_phone": _normalize_phone(str(phone)),
        "prefill_text": (str(prefill).strip() or DEFAULT_PREFILL),
    }


def _write_local(settings: dict[str, str]) -> None:
    path = Path(EVENT_LINK_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def get_event_link_settings() -> dict[str, str]:
    if _gcs_enabled():
        from google.cloud import storage

        client = storage.Client()
        blob = client.bucket(FAQ_GCS_BUCKET).blob(EVENT_LINK_GCS_OBJECT)
        if blob.exists():
            try:
                data = json.loads(blob.download_as_text(encoding="utf-8"))
                return {
                    "bot_phone": _normalize_phone(str(data.get("bot_phone") or "")),
                    "prefill_text": (
                        str(data.get("prefill_text") or "").strip() or DEFAULT_PREFILL
                    ),
                }
            except (json.JSONDecodeError, OSError):
                logger.exception(
                    "Failed reading gs://%s/%s",
                    FAQ_GCS_BUCKET,
                    EVENT_LINK_GCS_OBJECT,
                )
        # Seed from local defaults / bake if missing.
        settings = _read_local()
        set_event_link_settings(
            bot_phone=settings["bot_phone"],
            prefill_text=settings["prefill_text"],
        )
        return settings

    return _read_local()


def set_event_link_settings(*, bot_phone: str, prefill_text: str) -> dict[str, str]:
    settings = {
        "bot_phone": _normalize_phone(bot_phone),
        "prefill_text": (prefill_text or "").strip() or DEFAULT_PREFILL,
    }

    if _gcs_enabled():
        from google.cloud import storage

        client = storage.Client()
        blob = client.bucket(FAQ_GCS_BUCKET).blob(EVENT_LINK_GCS_OBJECT)
        blob.upload_from_string(
            json.dumps(settings, indent=2) + "\n",
            content_type="application/json",
        )
        logger.info(
            "Wrote event link settings to gs://%s/%s",
            FAQ_GCS_BUCKET,
            EVENT_LINK_GCS_OBJECT,
        )

    _write_local(settings)
    return settings


def build_wa_me_link(bot_phone: str, prefill_text: str) -> str | None:
    phone = _normalize_phone(bot_phone)
    if not phone:
        return None
    text = (prefill_text or "").strip() or DEFAULT_PREFILL
    return f"https://wa.me/{phone}?text={quote(text)}"


def build_group_paste_message(bot_phone: str, prefill_text: str) -> str | None:
    link = build_wa_me_link(bot_phone, prefill_text)
    if not link:
        return None
    subject = (prefill_text or "").strip() or DEFAULT_PREFILL
    headline = subject
    lower = subject.lower()
    for prefix in (
        "hi, i have a question about ",
        "hi i have a question about ",
        "i have a question about ",
        "question about ",
    ):
        if lower.startswith(prefix):
            headline = subject[len(prefix) :].strip(" ?")
            break
    return (
        f"🤖 Questions about {headline}?\n\n"
        f"Ask our Event Assistant anytime:\n"
        f"{link}"
    )


def event_link_view() -> dict[str, str | None]:
    settings = get_event_link_settings()
    link = build_wa_me_link(settings["bot_phone"], settings["prefill_text"])
    return {
        "bot_phone": settings["bot_phone"],
        "prefill_text": settings["prefill_text"],
        "wa_me_link": link,
        "group_message": build_group_paste_message(
            settings["bot_phone"], settings["prefill_text"]
        ),
        "storage": (
            f"gs://{FAQ_GCS_BUCKET}/{EVENT_LINK_GCS_OBJECT}"
            if _gcs_enabled()
            else str(EVENT_LINK_FILE)
        ),
        # Unused but handy if templates want FAQ object context.
        "faq_object": FAQ_GCS_OBJECT or None,
    }
