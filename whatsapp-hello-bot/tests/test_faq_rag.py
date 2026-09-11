import math
import os
from pathlib import Path

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""

from app.faq_rag import chunk_faq_text, retrieve_chunks
from app.faq_store import get_faq_text, set_faq_text


def test_chunk_faq_prefers_qa_blocks():
    text = (
        "Q: Where is parking?\nA: Lot C.\n\n"
        "Q: When do students arrive?\nA: 8:15 AM.\n"
    )
    chunks = chunk_faq_text(text)
    assert len(chunks) == 2
    assert "parking" in chunks[0].lower()
    assert "8:15" in chunks[1]


def test_chunk_faq_blank_line_sections():
    text = "Arrival:\nBe there by 8:15.\n\nParking:\nUse Lot C.\n"
    chunks = chunk_faq_text(text)
    assert len(chunks) == 2
    assert "Arrival" in chunks[0]
    assert "Parking" in chunks[1]


def test_local_faq_store_roundtrip(tmp_path):
    path = tmp_path / "faq.txt"
    set_faq_text("Hello FAQ", faq_path=path)
    assert get_faq_text(faq_path=path) == "Hello FAQ"


def test_retrieve_chunks_ranks_relevant(monkeypatch, tmp_path):
    faq_file = tmp_path / "faq.txt"
    faq_text = (
        "Q: Where should parents park?\nA: Parents should park in Lot C.\n\n"
        "Q: What should students bring for lunch?\nA: Bring a packed lunch.\n\n"
        "Q: Where is check-in?\nA: Check in at the main gym entrance.\n"
    )
    set_faq_text(faq_text, faq_path=faq_file)

    # Deterministic fake embeddings: one-hot-ish vectors per chunk + query.
    def fake_embed(texts, api_key=None):
        vectors = []
        for text in texts:
            lower = text.lower()
            if "park" in lower:
                vectors.append([1.0, 0.0, 0.0])
            elif "lunch" in lower:
                vectors.append([0.0, 1.0, 0.0])
            elif "check" in lower or "gym" in lower:
                vectors.append([0.0, 0.0, 1.0])
            else:
                vectors.append([0.2, 0.2, 0.2])
        return vectors

    monkeypatch.setattr("app.faq_rag.embed_texts", fake_embed)
    monkeypatch.setattr("app.faq_rag.OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("app.faq_rag.FAQ_SKIP_RAG_MAX_CHARS", 0)

    chunks = retrieve_chunks(
        "Where do I park?",
        faq_text=faq_text,
        top_k=1,
        faq_path=faq_file,
    )
    assert len(chunks) == 1
    assert "Lot C" in chunks[0]


def test_cosine_prefers_aligned_vectors():
    from app.faq_rag import _cosine

    assert _cosine([1, 0], [1, 0]) == 1.0
    assert math.isclose(_cosine([1, 0], [0, 1]), 0.0)


def test_small_faq_skips_embeddings(monkeypatch, tmp_path):
    faq_file = tmp_path / "faq.txt"
    faq_text = "Q: Where is parking?\nA: Lot C.\n"
    set_faq_text(faq_text, faq_path=faq_file)

    def boom(texts, api_key=None):
        raise AssertionError("embeddings should be skipped on small FAQ fast path")

    monkeypatch.setattr("app.faq_rag.embed_texts", boom)
    monkeypatch.setattr("app.faq_rag.FAQ_SKIP_RAG_MAX_CHARS", 12000)

    chunks = retrieve_chunks(
        "Where do I park?",
        faq_text=faq_text,
        faq_path=faq_file,
    )
    assert len(chunks) == 1
    assert "Lot C" in chunks[0]
    assert chunks[0].strip() == faq_text.strip()


def test_index_memory_cache(monkeypatch, tmp_path):
    from app import faq_rag

    faq_file = tmp_path / "faq.txt"
    faq_text = "Q: Parking?\nA: Lot C.\n\nQ: Lunch?\nA: Pack one.\n"
    set_faq_text(faq_text, faq_path=faq_file)
    monkeypatch.setattr("app.faq_rag.FAQ_SKIP_RAG_MAX_CHARS", 0)

    calls = {"n": 0}

    def fake_embed(texts, api_key=None):
        calls["n"] += 1
        return [[float(i), 0.0, 0.0] for i, _ in enumerate(texts)]

    monkeypatch.setattr("app.faq_rag.embed_texts", fake_embed)
    monkeypatch.setattr("app.faq_rag.OPENAI_API_KEY", "test-key")

    faq_rag.clear_index_cache()
    first = faq_rag.ensure_index(faq_text, faq_path=faq_file)
    # Second ensure with same text should use memory/local without rebuild;
    # embedding calls happen during rebuild only.
    rebuild_calls = calls["n"]
    second = faq_rag.ensure_index(faq_text, faq_path=faq_file)
    assert second["chunks"]
    assert calls["n"] == rebuild_calls
    assert first["chunks"][0]["text"]
