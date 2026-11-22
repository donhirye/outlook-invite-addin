"""Regression: structured FAQ row → one chunk with metadata (eng-rag step 1)."""

import os
from pathlib import Path

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""

from app.faq_rag import INDEX_VERSION, build_index_from_records, ensure_index
from app.faq_structured_chunks import (
    chunk_dict_from_record,
    chunk_faq_records,
    embedding_text_for_record,
    issue_folder_relpath,
)


def _row(**overrides):
    base = {
        "faq_id": "WEEKLY-20261030-001",
        "category": "Candy Donation",
        "question": "When can families donate candy?",
        "answer": "November 4 and 5.",
        "source": "Crone's Weekly Newsletter - 2026-10-30",
        "source_url": "",
        "published_date": "2026-10-30",
        "event_date": "2026-11-04 to 2026-11-05",
        "status": "Active",
    }
    base.update(overrides)
    return base


def test_one_row_one_chunk():
    rows = [
        _row(faq_id="WEEKLY-20261030-001", category="Candy Donation"),
        _row(
            faq_id="WEEKLY-20261030-002",
            category="School Schedule",
            question="Is there school on Monday?",
            answer="No student attendance.",
        ),
    ]
    report = chunk_faq_records(rows)
    assert report.included_count == 2
    assert report.excluded_count == 0
    assert [c["metadata"]["faq_id"] for c in report.included] == [
        "WEEKLY-20261030-001",
        "WEEKLY-20261030-002",
    ]


def test_metadata_retained_and_blank_url_becomes_issue_path():
    rec = _row(source_url="")
    chunk = chunk_dict_from_record(rec, chunk_id=0)
    meta = chunk["metadata"]
    assert meta["faq_id"] == "WEEKLY-20261030-001"
    assert meta["category"] == "Candy Donation"
    assert meta["source"] == "Crone's Weekly Newsletter - 2026-10-30"
    assert meta["published_date"] == "2026-10-30"
    assert meta["event_date"] == "2026-11-04 to 2026-11-05"
    assert meta["status"] == "Active"
    assert meta["source_url"] == (
        "newsletter_archive/issues/Crones_Weekly_Newsletter_2026-10-30"
    )
    assert "https://" not in meta["source_url"]


def test_written_source_url_preserved():
    rec = _row(source_url="https://example.com/issue")
    chunk = chunk_dict_from_record(rec, chunk_id=0)
    assert chunk["metadata"]["source_url"] == "https://example.com/issue"


def test_embedding_text_has_no_heading_leak_across_chunks():
    rows = [
        _row(faq_id="A1", category="Athletics", question="Q1?", answer="A1."),
        _row(faq_id="B1", category="Music", question="Q2?", answer="A2."),
    ]
    report = chunk_faq_records(rows)
    texts = [c["text"] for c in report.included]
    assert texts[0] == "Category: Athletics\nQ: Q1?\nA: A1."
    assert texts[1] == "Category: Music\nQ: Q2?\nA: A2."
    assert "##" not in texts[0] and "##" not in texts[1]
    # Next category must not appear glued onto the previous chunk.
    assert "Music" not in texts[0]
    assert "Athletics" not in texts[1]


def test_status_exclusions_reported():
    rows = [
        _row(faq_id="KEEP-1", status="Active"),
        _row(faq_id="KEEP-2", status="Needs_Review", question="Review me?", answer="Maybe."),
        _row(
            faq_id="SKIP-1",
            status="Retired",
            question="Old?",
            answer="Gone.",
        ),
    ]
    report = chunk_faq_records(rows)
    assert report.included_count == 2
    assert {c["metadata"]["faq_id"] for c in report.included} == {"KEEP-1", "KEEP-2"}
    assert report.excluded_count == 1
    assert report.excluded[0]["faq_id"] == "SKIP-1"
    assert "not in" in report.excluded[0]["reason"]


def test_ptsa_issue_folder_path():
    path = issue_folder_relpath(
        {
            "faq_id": "PTSA-20261104-001",
            "published_date": "2026-11-04",
            "source": "Crone PTSA Newsletter - 2026-11-04",
        }
    )
    assert path == "newsletter_archive/issues/Crone_PTSA_Newsletter_2026-11-04"


def test_build_index_embeds_structured_chunks(monkeypatch):
    rows = [
        _row(faq_id="WEEKLY-1", category="A", question="Q1?", answer="A1."),
        _row(faq_id="WEEKLY-2", category="B", question="Q2?", answer="A2."),
    ]

    def fake_embed(texts, api_key=None):
        return [[float(i), 0.0] for i, _ in enumerate(texts)]

    monkeypatch.setattr("app.faq_rag.embed_texts", fake_embed)
    index, report = build_index_from_records(rows)
    assert index["version"] == INDEX_VERSION
    assert index["source"] == "structured_records"
    assert len(index["chunks"]) == 2
    assert index["chunks"][0]["metadata"]["faq_id"] == "WEEKLY-1"
    assert index["chunks"][1]["text"] == embedding_text_for_record(rows[1])
    assert report.excluded_count == 0


def test_ensure_newsletter_rebuilds_when_csv_changes(monkeypatch, tmp_path):
    from app import faq_rag

    csv_path = tmp_path / "combined_FAQ_latest.csv"
    header = (
        "FAQ_ID,Category,Question,Answer,Source,Source_URL,"
        "Published_Date,Event_Date,Status\n"
    )
    csv_path.write_text(
        header
        + "WEEKLY-1,Cat,Q1?,A1.,Src,,2026-10-30,,Active\n",
        encoding="utf-8",
    )

    embeds = {"n": 0}

    def fake_embed(texts, api_key=None):
        embeds["n"] += 1
        return [[float(embeds["n"]), 0.0] for _ in texts]

    monkeypatch.setattr(faq_rag, "embed_texts", fake_embed)
    monkeypatch.setattr(faq_rag, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(faq_rag, "FAQ_GCS_BUCKET", "")
    faq_rag.clear_index_cache()

    first = faq_rag.ensure_newsletter_combined_index(csv_path=csv_path)
    assert first["source_sha256"]
    assert len(first["chunks"]) == 1
    first_calls = embeds["n"]

    # Unchanged CSV → reuse index (no new embed batch for rebuild).
    second = faq_rag.ensure_newsletter_combined_index(csv_path=csv_path)
    assert second["source_sha256"] == first["source_sha256"]
    assert embeds["n"] == first_calls

    # Update CSV → automatic rebuild.
    csv_path.write_text(
        header
        + "WEEKLY-1,Cat,Q1?,A1 updated.,Src,,2026-10-30,,Active\n"
        + "WEEKLY-2,Cat,Q2?,A2.,Src,,2026-10-30,,Needs_Review\n",
        encoding="utf-8",
    )
    faq_rag.clear_index_cache()
    third = faq_rag.ensure_newsletter_combined_index(csv_path=csv_path)
    assert third["source_sha256"] != first["source_sha256"]
    assert len(third["chunks"]) == 2
    assert embeds["n"] > first_calls
    assert "A1 updated" in third["chunks"][0]["text"]


def test_skip_zero_uses_structured_newsletter_index(monkeypatch):
    from app import faq_rag

    monkeypatch.setattr(faq_rag, "FAQ_SKIP_RAG_MAX_CHARS", 0)
    monkeypatch.setattr(faq_rag, "USE_NEWSLETTER_COMBINED_FAQ_INDEX", False)
    assert faq_rag.use_structured_newsletter_index(faq_path=None) is True
    # Test overrides with faq_path keep legacy text indexing.
    assert faq_rag.use_structured_newsletter_index(faq_path=Path("x.txt")) is False

    called = {"n": 0}

    def fake_ensure():
        called["n"] += 1
        return {
            "version": faq_rag.INDEX_VERSION,
            "chunks": [
                {
                    "id": 0,
                    "text": "Category: Parking\nQ: Where?\nA: Lot C.",
                    "embedding": [1.0, 0.0],
                    "metadata": {"faq_id": "WEEKLY-1"},
                }
            ],
        }

    monkeypatch.setattr(faq_rag, "ensure_newsletter_combined_index", fake_ensure)
    monkeypatch.setattr(
        faq_rag,
        "embed_texts",
        lambda texts, api_key=None: [[1.0, 0.0] for _ in texts],
    )
    monkeypatch.setattr(
        "app.faq_store.get_faq_text",
        lambda faq_path=None: "Q: ignore\nA: flat text path should not be used",
    )

    chunks = faq_rag.retrieve_chunks("Where do I park?")
    assert called["n"] == 1
    assert len(chunks) == 1
    assert chunks[0].startswith("Category: Parking")
    assert "##" not in chunks[0]


def test_ensure_index_rebuilds_when_schema_outdated(monkeypatch, tmp_path):
    faq_file = tmp_path / "faq.txt"
    faq_file.write_text("Q: Parking?\nA: Lot C.\n\nQ: Lunch?\nA: Pack one.\n", encoding="utf-8")
    stale = {
        "version": 1,
        "embedding_model": "test",
        "chunks": [{"id": 0, "text": "old", "embedding": [1.0]}],
    }
    index_path = Path(str(faq_file) + ".index.json")
    index_path.write_text(__import__("json").dumps(stale), encoding="utf-8")

    calls = {"n": 0}

    def fake_embed(texts, api_key=None):
        calls["n"] += 1
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr("app.faq_rag.embed_texts", fake_embed)
    monkeypatch.setattr("app.faq_rag.OPENAI_API_KEY", "test-key")
    from app import faq_rag

    faq_rag.clear_index_cache()
    index = faq_rag.ensure_index(faq_file.read_text(encoding="utf-8"), faq_path=faq_file)
    assert index["version"] == INDEX_VERSION
    assert calls["n"] >= 1
    assert len(index["chunks"]) >= 1
