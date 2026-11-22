"""FAQ chunking, embedding index, and retrieval (lightweight RAG).

Structured newsletter FAQs are chunked one row → one chunk with metadata.
Legacy flat FAQ text still uses Q:/A: parsing as a fallback.

On Cloud Run the newsletter combined CSV + index live under
``newsletter_archive/`` in the FAQ GCS bucket (same hierarchy as local).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from pathlib import Path
from typing import Any

from app.config import (
    FAQ_EMBEDDING_MODEL,
    FAQ_FILE,
    FAQ_GCS_BUCKET,
    FAQ_GCS_INDEX_OBJECT,
    FAQ_SKIP_RAG_MAX_CHARS,
    FAQ_TOP_K,
    NEWSLETTER_COMBINED_FAQ_GCS_OBJECT,
    NEWSLETTER_COMBINED_FAQ_INDEX_GCS_OBJECT,
    NEWSLETTER_COMBINED_FAQ_LOCAL,
    OPENAI_API_KEY,
    USE_NEWSLETTER_COMBINED_FAQ_INDEX,
)
from app.faq_structured_chunks import (
    ChunkBuildReport,
    chunk_faq_records,
    load_faq_csv_rows,
    load_faq_csv_text,
)

logger = logging.getLogger(__name__)

# v2: structured metadata on each chunk; old v1 indexes must rebuild.
INDEX_VERSION = 2

# Process-local index cache (keyed by FAQ text hash / source fingerprint).
_index_cache: dict[str, Any] | None = None
_index_cache_faq: str | None = None


def _gcs_enabled() -> bool:
    return bool(FAQ_GCS_BUCKET and FAQ_GCS_INDEX_OBJECT)


def _newsletter_gcs_enabled() -> bool:
    return bool(
        FAQ_GCS_BUCKET
        and NEWSLETTER_COMBINED_FAQ_GCS_OBJECT
        and NEWSLETTER_COMBINED_FAQ_INDEX_GCS_OBJECT
    )


def clear_index_cache() -> None:
    global _index_cache, _index_cache_faq
    _index_cache = None
    _index_cache_faq = None


def local_index_path(faq_path: Path | None = None) -> Path:
    base = Path(faq_path) if faq_path is not None else Path(FAQ_FILE)
    return base.with_suffix(base.suffix + ".index.json")


def newsletter_local_index_path(csv_path: Path | None = None) -> Path:
    base = Path(csv_path) if csv_path is not None else Path(NEWSLETTER_COMBINED_FAQ_LOCAL)
    return Path(str(base) + ".index.json")


def chunk_faq_text(text: str) -> list[str]:
    """Split FAQ into retrieval chunks (sections / Q&A blocks). Legacy path."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    # Prefer Q:/A: pairs as atomic chunks when present.
    qa_blocks = re.findall(
        r"(Q\s*:\s*.+?\s*A\s*:\s*.+?)(?=(?:\n\s*Q\s*:)|$)",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if len(qa_blocks) >= 2:
        chunks = [" ".join(block.split()).strip() for block in qa_blocks]
        return [c for c in chunks if c]

    # Otherwise split on blank lines; keep heading+body together when short.
    parts = re.split(r"\n\s*\n+", cleaned)
    chunks: list[str] = []
    for part in parts:
        piece = part.strip()
        if not piece:
            continue
        # Split very long sections by single newlines into smaller bites.
        if len(piece) > 900:
            lines = [ln.strip() for ln in piece.splitlines() if ln.strip()]
            buf: list[str] = []
            size = 0
            for line in lines:
                if buf and size + len(line) > 700:
                    chunks.append("\n".join(buf))
                    buf = [line]
                    size = len(line)
                else:
                    buf.append(line)
                    size += len(line) + 1
            if buf:
                chunks.append("\n".join(buf))
        else:
            chunks.append(piece)
    return chunks


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return -1.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def embed_texts(texts: list[str], *, api_key: str | None = None) -> list[list[float]]:
    """Embed texts with OpenAI. Overridable in tests via monkeypatch."""
    key = api_key if api_key is not None else OPENAI_API_KEY
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required to build the FAQ embedding index")
    if not texts:
        return []

    from openai import OpenAI

    client = OpenAI(api_key=key)
    response = client.embeddings.create(model=FAQ_EMBEDDING_MODEL, input=texts)
    # API returns data sorted by index, but be explicit.
    ordered = sorted(response.data, key=lambda item: item.index)
    return [list(item.embedding) for item in ordered]


def build_index(faq_text: str, *, api_key: str | None = None) -> dict[str, Any]:
    """Legacy: chunk flat FAQ text (no structured metadata)."""
    texts = chunk_faq_text(faq_text)
    embeddings = embed_texts(texts, api_key=api_key) if texts else []
    return {
        "version": INDEX_VERSION,
        "embedding_model": FAQ_EMBEDDING_MODEL,
        "source": "faq_text",
        "chunks": [
            {"id": idx, "text": text, "embedding": emb, "metadata": {}}
            for idx, (text, emb) in enumerate(zip(texts, embeddings))
        ],
    }


def build_index_from_records(
    records: list[dict[str, Any]],
    *,
    api_key: str | None = None,
    answerable_only: bool = True,
) -> tuple[dict[str, Any], ChunkBuildReport]:
    """One eligible structured row → one chunk with metadata."""
    report = chunk_faq_records(records, answerable_only=answerable_only)
    texts = [c["text"] for c in report.included]
    embeddings = embed_texts(texts, api_key=api_key) if texts else []
    chunks: list[dict[str, Any]] = []
    for chunk, emb in zip(report.included, embeddings):
        chunks.append(
            {
                "id": chunk["id"],
                "text": chunk["text"],
                "embedding": emb,
                "metadata": dict(chunk.get("metadata") or {}),
            }
        )
    index = {
        "version": INDEX_VERSION,
        "embedding_model": FAQ_EMBEDDING_MODEL,
        "source": "structured_records",
        "chunks": chunks,
        "exclusions": list(report.excluded),
    }
    return index, report


def _index_is_current(index: dict[str, Any] | None) -> bool:
    if not index or not index.get("chunks"):
        return False
    try:
        return int(index.get("version") or 0) == INDEX_VERSION
    except (TypeError, ValueError):
        return False


def _load_index_dict(
    *,
    faq_path: Path | None = None,
    gcs_object: str | None = None,
) -> dict[str, Any] | None:
    if faq_path is not None:
        path = (
            newsletter_local_index_path(faq_path)
            if faq_path.suffix == ".csv"
            else local_index_path(faq_path)
        )
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.exception("Failed reading local FAQ index %s", path)
            return None

    object_name = gcs_object or FAQ_GCS_INDEX_OBJECT
    if not FAQ_GCS_BUCKET or not object_name:
        path = local_index_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.exception("Failed reading local FAQ index %s", path)
            return None

    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(FAQ_GCS_BUCKET).blob(object_name)
    if not blob.exists():
        return None
    try:
        return json.loads(blob.download_as_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.exception(
            "Failed reading FAQ index gs://%s/%s",
            FAQ_GCS_BUCKET,
            object_name,
        )
        return None


def _save_index_dict(
    index: dict[str, Any],
    *,
    faq_path: Path | None = None,
    gcs_object: str | None = None,
    local_mirror: Path | None = None,
) -> None:
    payload = json.dumps(index) + "\n"

    if faq_path is not None:
        path = (
            newsletter_local_index_path(faq_path)
            if faq_path.suffix == ".csv"
            else local_index_path(faq_path)
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        logger.info("Wrote FAQ index to %s (%s chunks)", path, len(index.get("chunks") or []))
        return

    object_name = gcs_object or FAQ_GCS_INDEX_OBJECT
    if FAQ_GCS_BUCKET and object_name:
        from google.cloud import storage

        client = storage.Client()
        blob = client.bucket(FAQ_GCS_BUCKET).blob(object_name)
        blob.upload_from_string(payload, content_type="application/json")
        mirror = local_mirror or (
            newsletter_local_index_path()
            if object_name.endswith(".csv.index.json")
            or "newsletter_archive" in object_name
            else local_index_path()
        )
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(payload, encoding="utf-8")
        logger.info(
            "Wrote FAQ index to gs://%s/%s (%s chunks)",
            FAQ_GCS_BUCKET,
            object_name,
            len(index.get("chunks") or []),
        )
        return

    path = local_mirror or local_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    logger.info("Wrote FAQ index to %s (%s chunks)", path, len(index.get("chunks") or []))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_newsletter_combined_faq_bytes(
    csv_path: Path | None = None,
) -> tuple[bytes, str]:
    """Return (csv_bytes, source_label). Prefer local file when present, else GCS."""
    path = Path(csv_path) if csv_path is not None else Path(NEWSLETTER_COMBINED_FAQ_LOCAL)
    if path.exists():
        return path.read_bytes(), str(path)
    if FAQ_GCS_BUCKET and NEWSLETTER_COMBINED_FAQ_GCS_OBJECT:
        from google.cloud import storage

        blob = (
            storage.Client()
            .bucket(FAQ_GCS_BUCKET)
            .blob(NEWSLETTER_COMBINED_FAQ_GCS_OBJECT)
        )
        if blob.exists():
            uri = f"gs://{FAQ_GCS_BUCKET}/{NEWSLETTER_COMBINED_FAQ_GCS_OBJECT}"
            return blob.download_as_bytes(), uri
    raise FileNotFoundError(
        f"Combined FAQ CSV not found locally ({path}) or in GCS "
        f"({FAQ_GCS_BUCKET}/{NEWSLETTER_COMBINED_FAQ_GCS_OBJECT})"
    )


def upload_newsletter_combined_faq_csv(
    csv_path: Path | None = None,
    *,
    gcs_object: str | None = None,
    csv_bytes: bytes | None = None,
) -> str:
    """Upload combined FAQ CSV to staging/prod FAQ bucket under newsletter_archive/."""
    if not FAQ_GCS_BUCKET:
        raise RuntimeError("FAQ_GCS_BUCKET is required to upload the combined FAQ CSV")
    object_name = gcs_object or NEWSLETTER_COMBINED_FAQ_GCS_OBJECT
    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(FAQ_GCS_BUCKET).blob(object_name)
    if csv_bytes is not None:
        blob.upload_from_string(csv_bytes, content_type="text/csv; charset=utf-8")
    else:
        path = Path(csv_path) if csv_path is not None else Path(NEWSLETTER_COMBINED_FAQ_LOCAL)
        if not path.exists():
            raise FileNotFoundError(f"Combined FAQ CSV not found: {path}")
        blob.upload_from_filename(str(path), content_type="text/csv; charset=utf-8")
    uri = f"gs://{FAQ_GCS_BUCKET}/{object_name}"
    logger.info("Uploaded combined FAQ CSV to %s", uri)
    return uri


def load_newsletter_combined_faq_rows(
    *,
    csv_path: Path | None = None,
    prefer_gcs: bool = False,
) -> list[dict[str, Any]]:
    """Load combined FAQ rows from GCS (if enabled) or local CSV."""
    if prefer_gcs and _newsletter_gcs_enabled():
        from google.cloud import storage

        blob = (
            storage.Client()
            .bucket(FAQ_GCS_BUCKET)
            .blob(NEWSLETTER_COMBINED_FAQ_GCS_OBJECT)
        )
        if blob.exists():
            return load_faq_csv_text(blob.download_as_text(encoding="utf-8-sig"))

    path = Path(csv_path) if csv_path is not None else Path(NEWSLETTER_COMBINED_FAQ_LOCAL)
    return load_faq_csv_rows(path)


def _index_matches_csv(index: dict[str, Any] | None, source_sha256: str) -> bool:
    if not _index_is_current(index):
        return False
    return (index or {}).get("source_sha256") == source_sha256


def rebuild_index(faq_text: str, *, faq_path: Path | None = None) -> dict[str, Any]:
    """Build embeddings for faq_text and persist the index next to the FAQ."""
    global _index_cache, _index_cache_faq

    index = build_index(faq_text)
    _save_index_dict(index, faq_path=faq_path)
    cleaned = (faq_text or "").strip()
    _index_cache = index
    _index_cache_faq = cleaned
    return index


def rebuild_newsletter_combined_index(
    *,
    csv_path: Path | None = None,
    api_key: str | None = None,
    upload_csv: bool = True,
    write_gcs: bool = True,
    csv_bytes: bytes | None = None,
    source_label: str | None = None,
    sync_faq_records: bool = True,
) -> tuple[dict[str, Any], ChunkBuildReport]:
    """Chunk combined_FAQ_latest.csv, sync live faq_records.json, write index.

    Standard procedure when the combined FAQ CSV changes: replace live FAQ
    records from the CSV (same source as chunks), then rebuild embeddings.
    """
    global _index_cache, _index_cache_faq

    path = Path(csv_path) if csv_path is not None else Path(NEWSLETTER_COMBINED_FAQ_LOCAL)
    if csv_bytes is None:
        csv_bytes, source_label = read_newsletter_combined_faq_bytes(path)
    elif source_label is None:
        source_label = str(path)

    source_sha = _sha256_bytes(csv_bytes)
    text = csv_bytes.decode("utf-8-sig")
    rows = load_faq_csv_text(text)

    records_sync: dict[str, Any] | None = None
    if sync_faq_records:
        from app.faq_records import replace_faq_records_from_rows

        records_sync = replace_faq_records_from_rows(rows)
        logger.info(
            "Synced live faq_records from combined FAQ (%s rows, mode=%s)",
            records_sync.get("imported"),
            records_sync.get("mode"),
        )

    index, report = build_index_from_records(rows, api_key=api_key)
    index["source_sha256"] = source_sha
    index["source_label"] = source_label
    if records_sync is not None:
        index["faq_records_synced"] = records_sync.get("imported")

    local_mirror = newsletter_local_index_path(path)
    if write_gcs and FAQ_GCS_BUCKET:
        if upload_csv:
            # Keep GCS CSV in sync when we rebuilt from local bytes.
            if path.exists():
                upload_newsletter_combined_faq_csv(path, csv_bytes=csv_bytes)
            else:
                upload_newsletter_combined_faq_csv(csv_bytes=csv_bytes)
        _save_index_dict(
            index,
            gcs_object=NEWSLETTER_COMBINED_FAQ_INDEX_GCS_OBJECT,
            local_mirror=local_mirror,
        )
    else:
        _save_index_dict(index, faq_path=path)

    _index_cache = index
    _index_cache_faq = f"newsletter:{source_sha}"
    logger.info(
        "Newsletter combined index: %s included, %s excluded (sha256=%s…)",
        report.included_count,
        report.excluded_count,
        source_sha[:12],
    )
    return index, report


def ensure_index(faq_text: str, *, faq_path: Path | None = None) -> dict[str, Any]:
    """Load index if present and current; otherwise rebuild from faq_text."""
    global _index_cache, _index_cache_faq

    cleaned = (faq_text or "").strip()
    if (
        faq_path is None
        and _index_cache is not None
        and _index_cache_faq == cleaned
        and _index_is_current(_index_cache)
    ):
        return _index_cache

    existing = _load_index_dict(faq_path=faq_path)
    if _index_is_current(existing):
        if faq_path is None:
            _index_cache = existing
            _index_cache_faq = cleaned
        return existing  # type: ignore[return-value]

    if existing and not _index_is_current(existing):
        logger.info(
            "FAQ embedding index schema outdated (version=%s, want=%s); rebuilding",
            existing.get("version"),
            INDEX_VERSION,
        )
    else:
        logger.info("FAQ embedding index missing; rebuilding")
    return rebuild_index(faq_text, faq_path=faq_path)


def ensure_newsletter_combined_index(
    *,
    csv_path: Path | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Load structured newsletter index; rebuild if missing, outdated, or CSV changed."""
    global _index_cache, _index_cache_faq

    path = Path(csv_path) if csv_path is not None else Path(NEWSLETTER_COMBINED_FAQ_LOCAL)
    csv_bytes, source_label = read_newsletter_combined_faq_bytes(path)
    source_sha = _sha256_bytes(csv_bytes)
    cache_key = f"newsletter:{source_sha}"

    if (
        _index_cache is not None
        and _index_cache_faq == cache_key
        and _index_matches_csv(_index_cache, source_sha)
    ):
        return _index_cache

    existing = None
    if FAQ_GCS_BUCKET:
        existing = _load_index_dict(gcs_object=NEWSLETTER_COMBINED_FAQ_INDEX_GCS_OBJECT)
    if existing is None:
        existing = _load_index_dict(faq_path=path)

    if _index_matches_csv(existing, source_sha):
        _index_cache = existing
        _index_cache_faq = cache_key
        return existing  # type: ignore[return-value]

    if existing and _index_is_current(existing) and existing.get("source_sha256") != source_sha:
        logger.info(
            "Newsletter FAQ CSV changed (index sha=%s, csv sha=%s); rebuilding chunks",
            str(existing.get("source_sha256") or "")[:12],
            source_sha[:12],
        )
    elif existing and not _index_is_current(existing):
        logger.info(
            "Newsletter FAQ index schema outdated (version=%s, want=%s); rebuilding",
            existing.get("version"),
            INDEX_VERSION,
        )
    else:
        logger.info("Newsletter FAQ index missing; rebuilding")

    index, _report = rebuild_newsletter_combined_index(
        csv_path=path,
        api_key=api_key,
        upload_csv=bool(FAQ_GCS_BUCKET),
        write_gcs=bool(FAQ_GCS_BUCKET),
        csv_bytes=csv_bytes,
        source_label=source_label,
    )
    _index_cache_faq = cache_key
    return index


def use_structured_newsletter_index(*, faq_path: Path | None = None) -> bool:
    """Prefer combined_FAQ structured chunks over flat-text reparse.

    True when explicitly enabled, or when FAQ_SKIP_RAG_MAX_CHARS is 0 (always
    RAG) on the live path (no faq_path test override).
    """
    if faq_path is not None:
        return False
    if USE_NEWSLETTER_COMBINED_FAQ_INDEX:
        return True
    return FAQ_SKIP_RAG_MAX_CHARS == 0


def retrieve_chunks(
    question: str,
    *,
    faq_text: str | None = None,
    top_k: int | None = None,
    faq_path: Path | None = None,
) -> list[str]:
    """Return the top-k FAQ chunks most relevant to the question."""
    from app.faq_store import get_faq_text

    text = faq_text if faq_text is not None else get_faq_text(faq_path=faq_path)
    k = top_k if top_k is not None else FAQ_TOP_K
    k = max(1, int(k))

    # Fast path: small FAQs skip the embedding round-trip entirely.
    # SKIP=0 disables this and always retrieves from the embedding index.
    if FAQ_SKIP_RAG_MAX_CHARS > 0 and len(text) <= FAQ_SKIP_RAG_MAX_CHARS:
        logger.info(
            "FAQ fast path (chars=%s <= %s); skipping embeddings",
            len(text),
            FAQ_SKIP_RAG_MAX_CHARS,
        )
        return [text]

    try:
        if use_structured_newsletter_index(faq_path=faq_path):
            # One CSV/record row → one chunk (eng-rag); not flat-text parsing.
            index = ensure_newsletter_combined_index()
        else:
            index = ensure_index(text, faq_path=faq_path)
        chunks = index.get("chunks") or []
        if not chunks:
            return chunk_faq_text(text)[:k] or [text]

        query_emb = embed_texts([(question or "").strip() or " "])[0]
        scored: list[tuple[float, str]] = []
        for item in chunks:
            emb = item.get("embedding") or []
            body = (item.get("text") or "").strip()
            if not body or not emb:
                continue
            scored.append((_cosine(query_emb, emb), body))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        picked = [body for score, body in scored[:k] if score > 0]
        if picked:
            return picked
    except Exception:
        logger.exception("FAQ retrieval failed; falling back to full FAQ text")

    # Safe fallback: send the whole FAQ (small events) rather than fail closed.
    return [text]
