"""Durable FAQ text storage (local file or GCS).

When FAQ_GCS_BUCKET is set, the FAQ lives in Cloud Storage so Cloud Run
instances, the admin UI, and WhatsApp /faq all share the same source of truth.
Otherwise the local data/science_olympiad_faq.txt file is used.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import FAQ_FILE, FAQ_GCS_BUCKET, FAQ_GCS_OBJECT

logger = logging.getLogger(__name__)

# Process-local cache so Cloud Run warm instances avoid repeated disk/GCS reads.
_faq_text_cache: str | None = None


def _gcs_enabled() -> bool:
    return bool(FAQ_GCS_BUCKET and FAQ_GCS_OBJECT)


def _local_seed_text() -> str:
    path = Path(FAQ_FILE)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _gcs_client():
    from google.cloud import storage

    return storage.Client()


def _gcs_blob():
    client = _gcs_client()
    bucket = client.bucket(FAQ_GCS_BUCKET)
    return bucket.blob(FAQ_GCS_OBJECT)


def clear_faq_cache() -> None:
    global _faq_text_cache
    _faq_text_cache = None


def get_faq_text(*, faq_path: Path | None = None) -> str:
    """Return the current FAQ text.

    faq_path overrides storage and always reads that local file (tests).
    """
    global _faq_text_cache

    if faq_path is not None:
        if not faq_path.exists():
            raise FileNotFoundError(f"FAQ file not found: {faq_path}")
        text = faq_path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"FAQ file is empty: {faq_path}")
        return text

    if _faq_text_cache is not None:
        return _faq_text_cache

    if _gcs_enabled():
        blob = _gcs_blob()
        if blob.exists():
            text = blob.download_as_text(encoding="utf-8").strip()
            if not text:
                raise ValueError(
                    f"FAQ object is empty: gs://{FAQ_GCS_BUCKET}/{FAQ_GCS_OBJECT}"
                )
            _faq_text_cache = text
            return text

        # First boot: seed GCS from the image's baked FAQ file.
        seed = _local_seed_text().strip()
        if not seed:
            raise FileNotFoundError(
                f"FAQ missing in GCS (gs://{FAQ_GCS_BUCKET}/{FAQ_GCS_OBJECT}) "
                f"and no local seed at {FAQ_FILE}"
            )
        logger.info(
            "Seeding FAQ into gs://%s/%s from local bake",
            FAQ_GCS_BUCKET,
            FAQ_GCS_OBJECT,
        )
        set_faq_text(seed)
        return seed

    path = Path(FAQ_FILE)
    if not path.exists():
        raise FileNotFoundError(f"FAQ file not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"FAQ file is empty: {path}")
    _faq_text_cache = text
    return text


def set_faq_text(text: str, *, faq_path: Path | None = None) -> str:
    """Replace the FAQ text. Returns the cleaned text written."""
    global _faq_text_cache

    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("FAQ text cannot be empty")

    if faq_path is not None:
        faq_path.parent.mkdir(parents=True, exist_ok=True)
        faq_path.write_text(cleaned + "\n", encoding="utf-8")
        # Tests use faq_path overrides; don't poison the process cache.
        try:
            from app.faq_rag import clear_index_cache

            clear_index_cache()
        except Exception:
            logger.exception("Failed clearing FAQ index cache after save")
        return cleaned

    if _gcs_enabled():
        blob = _gcs_blob()
        blob.upload_from_string(cleaned + "\n", content_type="text/plain; charset=utf-8")
        logger.info(
            "Wrote FAQ to gs://%s/%s (%s chars)",
            FAQ_GCS_BUCKET,
            FAQ_GCS_OBJECT,
            len(cleaned),
        )
        # Keep a local mirror so tools/logs that peek at FAQ_FILE still work.
        local = Path(FAQ_FILE)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(cleaned + "\n", encoding="utf-8")
        _faq_text_cache = cleaned
        try:
            from app.faq_rag import clear_index_cache

            clear_index_cache()
        except Exception:
            logger.exception("Failed clearing FAQ index cache after save")
        return cleaned

    path = Path(FAQ_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cleaned + "\n", encoding="utf-8")
    logger.info("Wrote FAQ to %s (%s chars)", path, len(cleaned))
    _faq_text_cache = cleaned
    try:
        from app.faq_rag import clear_index_cache

        clear_index_cache()
    except Exception:
        logger.exception("Failed clearing FAQ index cache after save")
    return cleaned


def faq_storage_label() -> str:
    if _gcs_enabled():
        return f"gs://{FAQ_GCS_BUCKET}/{FAQ_GCS_OBJECT}"
    return str(FAQ_FILE)
