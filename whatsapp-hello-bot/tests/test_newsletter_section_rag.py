"""Newsletter section chunks + optional FAQ-miss safety net."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""
os.environ["USE_NEWSLETTER_SECTION_RAG"] = "false"

from app import newsletter_section_chunks as chunks_mod
from app import newsletter_section_rag as section_rag
from app.engines import answer_path
from app.engines.base import ConversationContext
from app.faq_service import FaqAnswer


def test_parse_cleaned_sections_markdown_splits_headings():
    md = """# Title

## Clubs

Teachers of Tomorrow, Computer Science, Robotics, Chess, and ASL club are featured.

## Fees

A $10 fee is charged for all club participants.
"""
    sections = chunks_mod.parse_cleaned_sections_markdown(md)
    headings = [h for h, _ in sections]
    assert "Clubs" in headings
    assert "Fees" in headings
    clubs_body = dict(sections)["Clubs"]
    assert "Robotics" in clubs_body


def test_chunk_issue_folder_from_cleaned_sections(tmp_path):
    folder = tmp_path / "Crones_Weekly_Newsletter_2026-09-11"
    folder.mkdir()
    (folder / "Crones_Weekly_Newsletter_2026-09-11_Metadata.json").write_text(
        '{"issue_date":"2026-09-11","subject":"Crone\'s Weekly Newsletter"}',
        encoding="utf-8",
    )
    (folder / "Crones_Weekly_Newsletter_2026-09-11_Cleaned_Sections.md").write_text(
        "## Student Clubs\n\n"
        "The clubs featured are Teachers of Tomorrow, Computer Science, "
        "Robotics, Chess, and ASL club. A $10 fee is charged for participants.\n",
        encoding="utf-8",
    )
    out = chunks_mod.chunk_issue_folder(folder)
    assert len(out) == 1
    assert "ASL club" in out[0]["text"]
    assert out[0]["metadata"]["issue_date"] == "2026-09-11"
    assert "Weekly Newsletter" in out[0]["metadata"]["source"]


def test_section_rag_disabled_by_default(monkeypatch):
    monkeypatch.setattr(section_rag, "USE_NEWSLETTER_SECTION_RAG", False)
    assert section_rag.section_rag_enabled() is False
    assert section_rag.answer_from_newsletter_sections("what clubs exist?") is None


def test_answer_path_skips_sections_when_flag_off(monkeypatch):
    monkeypatch.setattr(
        "app.config.USE_NEWSLETTER_SECTION_RAG",
        False,
        raising=False,
    )

    class Eng:
        id = "engine1_legacy"
        version = "test"

    calls = {"section": 0}

    def fake_faq(text, allow_rag=True):
        return FaqAnswer(
            answer="I couldn't find that information in the event FAQ. "
            "Please contact the PTSA Administrators.",
            retrieval_mode="rag",
            llm_invocations=1,
        )

    def boom_section(text):
        calls["section"] += 1
        raise AssertionError("section RAG must not run when flag is off")

    monkeypatch.setattr(answer_path, "answer_faq_detailed", fake_faq)
    monkeypatch.setattr(
        answer_path,
        "lookup_calendar_for_topic",
        lambda text: {"hit": False},
    )
    monkeypatch.setattr(
        "app.engines.answer_builders.overview_result",
        lambda ctx, engine=None: None,
    )
    monkeypatch.setattr(
        "app.engines.answer_builders.help_or_privacy",
        lambda ctx, engine=None: None,
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "app.newsletter_section_rag",
        type(
            "M",
            (),
            {"answer_from_newsletter_sections": staticmethod(boom_section)},
        )(),
    )
    # Force import path inside answer() to see flag false via config module
    import app.config as config

    monkeypatch.setattr(config, "USE_NEWSLETTER_SECTION_RAG", False)

    ctx = ConversationContext(
        phone_hash="h",
        phone="15550100001",
        message_id="m1",
        text="what clubs exist?",
    )
    out = answer_path.answer(ctx, engine=Eng())
    assert "couldn't find" in out.messages[0].lower()
    assert calls["section"] == 0


def test_answer_path_uses_sections_after_faq_miss_when_enabled(monkeypatch):
    import app.config as config

    monkeypatch.setattr(config, "USE_NEWSLETTER_SECTION_RAG", True)

    class Eng:
        id = "engine1_legacy"
        version = "test"

    def fake_faq(text, allow_rag=True):
        return FaqAnswer(
            answer="I couldn't find that information in the event FAQ. "
            "Please contact the PTSA Administrators.",
            retrieval_mode="rag",
            llm_invocations=1,
        )

    def fake_section(text):
        return FaqAnswer(
            answer=(
                "Featured clubs include Teachers of Tomorrow, Computer Science, "
                "Robotics, Chess, and ASL."
            ),
            retrieval_mode="newsletter_sections",
            llm_invocations=1,
            source_name="Crone's Weekly Newsletter - 2026-09-11",
            retrieved_chunks=["Section: Clubs\nASL club"],
        )

    monkeypatch.setattr(answer_path, "answer_faq_detailed", fake_faq)
    monkeypatch.setattr(
        answer_path,
        "lookup_calendar_for_topic",
        lambda text: {"hit": False},
    )
    monkeypatch.setattr(
        "app.engines.answer_builders.overview_result",
        lambda ctx, engine=None: None,
    )
    monkeypatch.setattr(
        "app.engines.answer_builders.help_or_privacy",
        lambda ctx, engine=None: None,
    )
    monkeypatch.setattr(
        "app.newsletter_section_rag.answer_from_newsletter_sections",
        fake_section,
    )

    ctx = ConversationContext(
        phone_hash="h",
        phone="15550100001",
        message_id="m2",
        text="what clubs exist?",
    )
    out = answer_path.answer(ctx, engine=Eng())
    assert "ASL" in out.messages[0]
    assert out.retrieval_mode == "newsletter_sections"
    assert out.sources == ["newsletter_sections"]


def test_faq_fully_answers_rejects_fall_fest_club_pointer():
    from app.engines.answer_builders import faq_fully_answers

    fall_fest = (
        "Fall Fest is Tuesday, September 1, 2026, from 3:10 PM to 4:00 PM at Crone. "
        "Students and parents can learn about Crone clubs, activities, and athletics."
    )
    assert faq_fully_answers("tell me about clubs at crone", fall_fest) is False
    assert faq_fully_answers("what was the fall fest event about?", fall_fest) is True
    named = (
        "Featured clubs include Teachers of Tomorrow, Computer Science, "
        "Robotics, Chess, and ASL."
    )
    assert faq_fully_answers("tell me about clubs at crone", named) is True


def test_weak_faq_opportunity_then_section_rag(monkeypatch):
    """Fall Fest pointer → keep searching sections; lead with the opportunity."""
    import app.config as config

    monkeypatch.setattr(config, "USE_NEWSLETTER_SECTION_RAG", True)

    class Eng:
        id = "engine1_legacy"
        version = "test"

    fall_fest = (
        "Fall Fest is Tuesday, September 1, 2026, from 3:10 PM to 4:00 PM at Crone. "
        "Students and parents can learn about Crone clubs, activities, and athletics."
    )
    calls = {"faq": 0}

    def fake_faq(text, allow_rag=True):
        calls["faq"] += 1
        if not allow_rag:
            return FaqAnswer(
                answer=fall_fest,
                retrieval_mode="direct_qa",
                match_score=0.68,
                confidence=0.68,
                faq_id="WEEKLY-20260807-006",
                source_name="Crone's Weekly Newsletter - 2026-08-07",
                llm_invocations=0,
            )
        return FaqAnswer(
            answer="I couldn't find that information in the event FAQ. "
            "Please contact the PTSA Administrators.",
            retrieval_mode="rag",
            llm_invocations=1,
        )

    def fake_section(text):
        return FaqAnswer(
            answer=(
                "Featured clubs include Teachers of Tomorrow, Computer Science, "
                "Robotics, Chess, and ASL."
            ),
            retrieval_mode="newsletter_sections",
            llm_invocations=1,
            source_name="Crone's Weekly Newsletter - 2026-09-11",
            retrieved_chunks=["Section: Clubs\nASL club"],
        )

    monkeypatch.setattr(answer_path, "answer_faq_detailed", fake_faq)
    monkeypatch.setattr(
        answer_path,
        "lookup_calendar_for_topic",
        lambda text: {"hit": False},
    )
    monkeypatch.setattr(
        "app.engines.answer_builders.overview_result",
        lambda ctx, engine=None: None,
    )
    monkeypatch.setattr(
        "app.engines.answer_builders.help_or_privacy",
        lambda ctx, engine=None: None,
    )
    monkeypatch.setattr(
        "app.newsletter_section_rag.answer_from_newsletter_sections",
        fake_section,
    )

    ctx = ConversationContext(
        phone_hash="h",
        phone="15550100001",
        message_id="m3",
        text="tell me about clubs at crone",
    )
    out = answer_path.answer(ctx, engine=Eng())
    assert calls["faq"] == 2
    assert "One opportunity:" in out.messages[0]
    assert "Fall Fest" in out.messages[0]
    assert "ASL" in out.messages[0]
    assert "Teachers of Tomorrow" in out.messages[0]


def test_build_section_index_uses_injected_embeddings(monkeypatch, tmp_path):
    issues = tmp_path / "issues"
    folder = issues / "Crones_Weekly_Newsletter_2026-09-11"
    folder.mkdir(parents=True)
    (folder / "x_Metadata.json").write_text(
        '{"issue_date":"2026-09-11"}', encoding="utf-8"
    )
    (folder / "x_Cleaned_Sections.md").write_text(
        "## Clubs\n\n"
        "Teachers of Tomorrow, Computer Science, Robotics, Chess, and ASL club.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        section_rag,
        "NEWSLETTER_SECTIONS_INDEX_LOCAL",
        tmp_path / "sections_index.json",
    )
    monkeypatch.setattr(section_rag, "FAQ_GCS_BUCKET", "")
    monkeypatch.setattr(
        section_rag,
        "embed_texts",
        lambda texts, api_key=None: [[0.1, 0.2, 0.3] for _ in texts],
    )
    index = section_rag.rebuild_section_index(
        issues_root=issues, write_gcs=False
    )
    assert len(index["chunks"]) == 1
    assert index["chunks"][0]["embedding"] == [0.1, 0.2, 0.3]
    assert (tmp_path / "sections_index.json").exists()
