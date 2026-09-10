"""FAQ chunking, embedding index, and retrieval (lightweight RAG).

Source of truth is still the FAQ text (via faq_store). The embedding index is
derived and rebuilt whenever the FAQ is saved. On Cloud Run the index is stored
next to the FAQ in GCS so every instance shares the same vectors.
"""

from __future__ import annotations

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
    FAQ_TOP_K,
    OPENAI_API_KEY,
)

logger = logging.getLogger(__name__)

INDEX_VERSION = 1


def _gcs_enabled() -> bool:
    return bool(FAQ_GCS_BUCKET and FAQ_GCS_INDEX_OBJECT)


def local_index_path(faq_path: Path | None = None) -> Path:
    base = Path(faq_path) if faq_path is not None else Path(FAQ_FILE)
    return base.with_suffix(base.suffix + ".index.json")


def chunk_faq_text(text: str) -> list[str]:
    """Split FAQ into retrieval chunks (sections / Q&A blocks)."""
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
    chunks = chunk_faq_text(faq_text)
    embeddings = embed_texts(chunks, api_key=api_key) if chunks else []
    return {
        "version": INDEX_VERSION,
        "embedding_model": FAQ_EMBEDDING_MODEL,
        "chunks": [
            {"id": idx, "text": text, "embedding": emb}
            for idx, (text, emb) in enumerate(zip(chunks, embeddings))
        ],
    }


def _load_index_dict(*, faq_path: Path | None = None) -> dict[str, Any] | None:
    if faq_path is not None or not _gcs_enabled():
        path = local_index_path(faq_path)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.exception("Failed reading local FAQ index %s", path)
            return None

    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(FAQ_GCS_BUCKET).blob(FAQ_GCS_INDEX_OBJECT)
    if not blob.exists():
        return None
    try:
        return json.loads(blob.download_as_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.exception(
            "Failed reading FAQ index gs://%s/%s",
            FAQ_GCS_BUCKET,
            FAQ_GCS_INDEX_OBJECT,
        )
        return None


def _save_index_dict(index: dict[str, Any], *, faq_path: Path | None = None) -> None:
    payload = json.dumps(index) + "\n"

    if faq_path is not None or not _gcs_enabled():
        path = local_index_path(faq_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        logger.info("Wrote FAQ index to %s (%s chunks)", path, len(index.get("chunks") or []))
        return

    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(FAQ_GCS_BUCKET).blob(FAQ_GCS_INDEX_OBJECT)
    blob.upload_from_string(payload, content_type="application/json")
    # Local mirror for debugging.
    mirror = local_index_path()
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(payload, encoding="utf-8")
    logger.info(
        "Wrote FAQ index to gs://%s/%s (%s chunks)",
        FAQ_GCS_BUCKET,
        FAQ_GCS_INDEX_OBJECT,
        len(index.get("chunks") or []),
    )


def rebuild_index(faq_text: str, *, faq_path: Path | None = None) -> dict[str, Any]:
    """Build embeddings for faq_text and persist the index next to the FAQ."""
    index = build_index(faq_text)
    _save_index_dict(index, faq_path=faq_path)
    return index


def ensure_index(faq_text: str, *, faq_path: Path | None = None) -> dict[str, Any]:
    """Load index if present; otherwise rebuild from faq_text."""
    existing = _load_index_dict(faq_path=faq_path)
    if existing and existing.get("chunks"):
        return existing
    logger.info("FAQ embedding index missing; rebuilding")
    return rebuild_index(faq_text, faq_path=faq_path)


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

    try:
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
