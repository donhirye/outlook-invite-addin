"""ANSWER_STRATEGY switch: A / C / E / Ep are separate modules."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""

import pytest

from app import calendar_store, guided_state
from app.eval_framework import list_strategies, normalize_strategy_id
from app.engines import engine1_legacy
from app.engines.base import ConversationContext

IMPORT_DIR = Path(__file__).resolve().parents[1] / "data" / "imports"
PHONE = "15550001111"
TODAY = date(2026, 11, 13)


def _ctx(text: str, *, strategy: str | None = None) -> ConversationContext:
    extras = {}
    if strategy:
        extras["answer_strategy"] = strategy
    return ConversationContext(
        phone_hash="hash",
        phone=PHONE,
        message_id="m",
        text=text,
        extras=extras,
    )


@pytest.fixture
def both(tmp_path, monkeypatch):
    monkeypatch.setattr(calendar_store, "CALENDAR_FILE", tmp_path / "calendar.json")
    monkeypatch.setattr(calendar_store, "FAQ_GCS_BUCKET", "")
    monkeypatch.setattr(guided_state, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(guided_state, "FAQ_GCS_BUCKET", "")
    calendar_store.clear_calendar_cache()
    calendar_store.import_calendar_csv_text(
        (IMPORT_DIR / "school_district_204_2026_2027_calendar.csv").read_text(
            encoding="utf-8-sig"
        )
    )
    calendar_store.import_calendar_csv_text(
        (IMPORT_DIR / "crone_2026_2027_calendar.csv").read_text(encoding="utf-8-sig")
    )
    yield
    calendar_store.clear_calendar_cache()


def _fake_faq(text: str, *args, allow_rag: bool = True, **kwargs):
    lowered = (text or "").lower()
    if "add the calendar" in lowered or "register" in lowered or "to my phone" in lowered:
        answer = "FAQ ANSWER"
        mode = "direct"
        score = 0.9
    else:
        # Simulate weak PTSA-website FAQ hit on "next meeting" asks.
        if "ptsa meeting" in lowered or "party in the park" in lowered:
            answer = (
                "The Crone PTSA website is www.CronePTSA.org. It includes meetings."
            )
            mode = "direct"
            score = 0.64
        else:
            answer = (
                "I couldn't find that information in the event FAQ. "
                "Please contact the PTSA Administrators."
            )
            mode = "direct_miss"
            score = 0.1
    return SimpleNamespace(
        answer=answer,
        source_name="faq",
        source_url="https://example.com/faq",
        llm_invocations=0,
        faq_id="F1",
        match_score=score,
        confidence=score,
        retrieval_mode=mode,
        retrieved_chunks=[],
        input_tokens=None,
        output_tokens=None,
    )


@pytest.fixture
def engine(both, monkeypatch):
    monkeypatch.setattr("app.config.EVAL_FRAMEWORK_ENABLED", True)
    monkeypatch.setattr("app.eval_framework.EVAL_FRAMEWORK_ENABLED", True, raising=False)
    monkeypatch.setattr("app.faq_service.answer_faq_detailed", _fake_faq)
    monkeypatch.setattr("app.eval_framework.strategy_a.answer_faq_detailed", _fake_faq)
    monkeypatch.setattr("app.eval_framework.strategy_c.answer_faq_detailed", _fake_faq)
    monkeypatch.setattr("app.eval_framework.strategy_e.answer_faq_detailed", _fake_faq)
    monkeypatch.setattr("app.eval_framework.strategy_ep.answer_faq_detailed", _fake_faq)
    return engine1_legacy.LegacyEngine()


def test_strategy_ids_listed():
    ids = {s["id"] for s in list_strategies()}
    assert ids == {"A", "C", "E", "Ep"}
    assert normalize_strategy_id("Eprime") == "Ep"
    assert normalize_strategy_id("e") == "E"


def test_framework_off_ignores_strategy_override(engine, monkeypatch):
    monkeypatch.setattr("app.config.EVAL_FRAMEWORK_ENABLED", False)
    out = engine.answer(
        _ctx("when is the next crone ptsa meeting", strategy="A")
    )
    # Flag off → always Ep (calendar wins), ignore A override.
    assert out.answer_strategy == "Ep"
    assert out.route == "calendar"


def test_strategy_a_party_without_when_misses_calendar_gate(engine):
    """Prod gate needs a time cue — Party in the Park without 'when' → FAQ."""
    out = engine.answer(_ctx("tell me more about the party in the park event", strategy="A"))
    assert out.answer_strategy == "A"
    # Fake FAQ returns website-ish hit for party asks → faq route
    assert out.route == "faq"


def test_strategy_e_party_hits_calendar(engine):
    out = engine.answer(_ctx("tell me more about the party in the park event", strategy="E"))
    assert out.answer_strategy == "E"
    # Calendar hit + weak FAQ hit → E merges
    assert out.route in {"calendar", "calendar_faq"}
    assert "Party in the Park" in out.messages[0]


def test_strategy_e_merges_ptsa_meeting_with_weak_faq(engine):
    out = engine.answer(_ctx("when is the next crone ptsa meeting", strategy="E"))
    assert out.route == "calendar_faq"
    assert "Jan 14, 2027" in out.messages[0]
    assert "CronePTSA.org" in out.messages[0] or "PTSA website" in out.messages[0]


def test_strategy_ep_calendar_wins_on_ptsa_meeting(engine):
    out = engine.answer(_ctx("when is the next crone ptsa meeting", strategy="Ep"))
    assert out.answer_strategy == "Ep"
    assert out.route == "calendar"
    assert "Jan 14, 2027" in out.messages[0]
    assert "CronePTSA.org" not in out.messages[0]


def test_strategy_ep_still_merges_how_to_register(engine):
    out = engine.answer(_ctx("how do I register for the color run", strategy="Ep"))
    assert out.route == "calendar_faq"
    assert "FAQ ANSWER" in out.messages[0]
