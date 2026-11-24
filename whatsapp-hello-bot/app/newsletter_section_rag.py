"""Optional newsletter HTML/section RAG — FAQ-miss safety net only.

Enabled only when USE_NEWSLETTER_SECTION_RAG is true. Default off.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from pathlib import Path
from typing import Any

from app.config import (
    FAQ_EMBEDDING_MODEL,
    FAQ_GCS_BUCKET,
    FAQ_TOP_K,
    NEWSLETTER_ISSUES_LOCAL,
    NEWSLETTER_SECTIONS_INDEX_GCS_OBJECT,
    NEWSLETTER_SECTIONS_INDEX_LOCAL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_REASONING_EFFORT,
    USE_NEWSLETTER_SECTION_RAG,
)
from app.faq_rag import embed_texts
from app.faq_service import FaqAnswer, strip_source_lines
from app.newsletter_section_chunks import collect_section_chunks

logger = logging.getLogger(__name__)

SECTION_INDEX_VERSION = 1

_SECTION_ANSWER_INSTRUCTIONS = """You are the Crone PTSA parent assistant answering from newsletter section excerpts only.
RULES:
1. Use ONLY the NEWSLETTER EXCERPTS plus TODAY'S DATE when comparing timing.
2. Do not invent clubs, fees, dates, links, or details that are not in the excerpts.
3. Answer ONLY what the parent asked. Drop unrelated sibling topics from the excerpts.
4. If excerpts conflict across issues, prefer the newest issue_date and say the FAQ/newsletter may have updated.
5. If the excerpts do not support the question, set answer to EXACTLY:
"I couldn't find that information in the event FAQ. Please contact the PTSA Administrators."
6. Keep answers concise (1–4 sentences). Do NOT add a Source: line.
7. Respond with JSON only, no markdown fences:
{"answer":"<parent-facing answer>","confidence":<number from 0 to 1>}"""

_index_cache: dict[str, Any] | None = None
_index_cache_key: str | None = None


def section_rag_enabled() -> bool:
    return bool(USE_NEWSLETTER_SECTION_RAG)


def clear_section_index_cache() -> None:
    global _index_cache, _index_cache_key
    _index_cache = None
    _index_cache_key = None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return -1.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _sha256_file_tree(issues_root: Path) -> str:
    """Fingerprint issue Source.html / Cleaned_Sections for rebuild detection."""
    h = hashlib.sha256()
    root = Path(issues_root)
    if not root.is_dir():
        return h.hexdigest()
    paths: list[Path] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        for pattern in ("*_Source.html", "*_Cleaned_Sections.md", "*_Metadata.json"):
            paths.extend(sorted(folder.glob(pattern)))
    for path in paths:
        h.update(path.name.encode("utf-8"))
        try:
            h.update(path.read_bytes())
        except OSError:
            continue
    return h.hexdigest()


def build_section_index(
    *,
    issues_root: Path | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    root = Path(issues_root) if issues_root is not None else Path(NEWSLETTER_ISSUES_LOCAL)
    chunks = collect_section_chunks(root)
    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts, api_key=api_key) if texts else []
    out_chunks: list[dict[str, Any]] = []
    for chunk, emb in zip(chunks, embeddings):
        out_chunks.append(
            {
                "id": chunk["id"],
                "text": chunk["text"],
                "embedding": emb,
                "metadata": dict(chunk.get("metadata") or {}),
            }
        )
    return {
        "version": SECTION_INDEX_VERSION,
        "embedding_model": FAQ_EMBEDDING_MODEL,
        "source": "newsletter_sections",
        "source_sha256": _sha256_file_tree(root),
        "issues_root": str(root),
        "chunks": out_chunks,
    }


def _load_section_index() -> dict[str, Any] | None:
    path = Path(NEWSLETTER_SECTIONS_INDEX_LOCAL)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.exception("Failed reading section index %s", path)
    if FAQ_GCS_BUCKET and NEWSLETTER_SECTIONS_INDEX_GCS_OBJECT:
        try:
            from google.cloud import storage

            blob = (
                storage.Client()
                .bucket(FAQ_GCS_BUCKET)
                .blob(NEWSLETTER_SECTIONS_INDEX_GCS_OBJECT)
            )
            if blob.exists():
                return json.loads(blob.download_as_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed reading section index from GCS")
    return None


def _save_section_index(
    index: dict[str, Any],
    *,
    write_gcs: bool = True,
) -> Path:
    path = Path(NEWSLETTER_SECTIONS_INDEX_LOCAL)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(index) + "\n"
    path.write_text(payload, encoding="utf-8")
    if write_gcs and FAQ_GCS_BUCKET and NEWSLETTER_SECTIONS_INDEX_GCS_OBJECT:
        from google.cloud import storage

        blob = (
            storage.Client()
            .bucket(FAQ_GCS_BUCKET)
            .blob(NEWSLETTER_SECTIONS_INDEX_GCS_OBJECT)
        )
        blob.upload_from_string(payload, content_type="application/json")
        logger.info(
            "Uploaded section index gs://%s/%s (%s chunks)",
            FAQ_GCS_BUCKET,
            NEWSLETTER_SECTIONS_INDEX_GCS_OBJECT,
            len(index.get("chunks") or []),
        )
    logger.info("Wrote section index %s (%s chunks)", path, len(index.get("chunks") or []))
    return path


def rebuild_section_index(
    *,
    issues_root: Path | None = None,
    api_key: str | None = None,
    write_gcs: bool = True,
) -> dict[str, Any]:
    global _index_cache, _index_cache_key
    index = build_section_index(issues_root=issues_root, api_key=api_key)
    _save_section_index(index, write_gcs=write_gcs)
    _index_cache = index
    _index_cache_key = str(index.get("source_sha256") or "")
    return index


def ensure_section_index(
    *,
    issues_root: Path | None = None,
    api_key: str | None = None,
) -> dict[str, Any] | None:
    """Load section index; rebuild from local issues when fingerprint drifts."""
    global _index_cache, _index_cache_key
    if not section_rag_enabled():
        return None
    root = Path(issues_root) if issues_root is not None else Path(NEWSLETTER_ISSUES_LOCAL)
    want_sha = _sha256_file_tree(root) if root.is_dir() else ""

    if (
        _index_cache is not None
        and int(_index_cache.get("version") or 0) == SECTION_INDEX_VERSION
        and (not want_sha or _index_cache.get("source_sha256") == want_sha)
    ):
        return _index_cache

    existing = _load_section_index()
    if (
        existing
        and int(existing.get("version") or 0) == SECTION_INDEX_VERSION
        and existing.get("chunks")
        and (not want_sha or existing.get("source_sha256") == want_sha)
    ):
        _index_cache = existing
        _index_cache_key = str(existing.get("source_sha256") or "")
        return existing

    if root.is_dir() and any(root.iterdir()):
        try:
            return rebuild_section_index(
                issues_root=root, api_key=api_key, write_gcs=False
            )
        except Exception:
            logger.exception("Failed rebuilding newsletter section index")
            return existing
    return existing


def retrieve_section_chunks(
    question: str,
    *,
    top_k: int | None = None,
    index: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return top-k section chunk dicts (text + metadata)."""
    if not section_rag_enabled():
        return []
    idx = index if index is not None else ensure_section_index()
    if not idx:
        return []
    chunks = idx.get("chunks") or []
    if not chunks:
        return []
    k = max(1, int(top_k if top_k is not None else FAQ_TOP_K))
    query_emb = embed_texts([(question or "").strip() or " "])[0]
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in chunks:
        emb = item.get("embedding") or []
        body = (item.get("text") or "").strip()
        if not body or not emb:
            continue
        scored.append((_cosine(query_emb, emb), item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for score, item in scored[:k] if score > 0]


def answer_from_newsletter_sections(question: str) -> FaqAnswer | None:
    """FAQ-miss fallback: retrieve newsletter sections and answer with LLM trim."""
    if not section_rag_enabled():
        return None
    if not OPENAI_API_KEY:
        return None
    q = (question or "").strip()
    if not q:
        return None
    try:
        hits = retrieve_section_chunks(q)
    except Exception:
        logger.exception("Newsletter section retrieval failed")
        return None
    if not hits:
        return None

    from openai import OpenAI

    from app.faq_records import chicago_today

    excerpts = "\n\n---\n\n".join(
        (h.get("text") or "").strip() for h in hits if (h.get("text") or "").strip()
    )
    today = chicago_today()
    user_input = (
        f"TODAY'S DATE (America/Chicago): {today.isoformat()} "
        f"({today.strftime('%A, %B %d, %Y')})\n\n"
        f"NEWSLETTER EXCERPTS:\n{excerpts}\n\n"
        f"PARENT QUESTION:\n{q}"
    )
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        create_kwargs: dict[str, Any] = {
            "model": OPENAI_MODEL,
            "instructions": _SECTION_ANSWER_INSTRUCTIONS,
            "input": user_input,
        }
        if not str(OPENAI_MODEL).startswith("gpt-5"):
            create_kwargs["temperature"] = 0
        if OPENAI_REASONING_EFFORT:
            create_kwargs["reasoning"] = {"effort": OPENAI_REASONING_EFFORT}
        try:
            response = client.responses.create(**create_kwargs)
        except Exception as exc:
            msg = str(exc).lower()
            retried = False
            if "temperature" in msg and "temperature" in create_kwargs:
                create_kwargs.pop("temperature", None)
                retried = True
            if "reasoning" in msg and "reasoning" in create_kwargs:
                create_kwargs.pop("reasoning", None)
                retried = True
            if not retried:
                raise
            response = client.responses.create(**create_kwargs)
    except Exception:
        logger.exception("Newsletter section LLM answer failed")
        return None

    raw = (getattr(response, "output_text", None) or "").strip()
    if not raw:
        for item in getattr(response, "output", None) or []:
            for part in getattr(item, "content", None) or []:
                t = getattr(part, "text", None)
                if t:
                    raw = str(t).strip()
                    break
            if raw:
                break
    answer = ""
    confidence: float | None = None
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            answer = str(payload.get("answer") or "").strip()
            conf = payload.get("confidence")
            if isinstance(conf, (int, float)):
                confidence = float(conf)
    except json.JSONDecodeError:
        answer = raw
    answer = strip_source_lines(answer)
    if not answer:
        return None

    meta0 = (hits[0].get("metadata") or {}) if hits else {}
    usage = getattr(response, "usage", None)
    return FaqAnswer(
        answer=answer,
        confidence=confidence,
        match_score=None,
        retrieval_mode="newsletter_sections",
        llm_invocations=1,
        source_name=str(meta0.get("source") or "") or None,
        source_url=str(meta0.get("source_url") or "") or None,
        input_tokens=getattr(usage, "input_tokens", None)
        if isinstance(getattr(usage, "input_tokens", None), int)
        else None,
        output_tokens=getattr(usage, "output_tokens", None)
        if isinstance(getattr(usage, "output_tokens", None), int)
        else None,
        retrieved_chunks=[(h.get("text") or "") for h in hits],
    )
