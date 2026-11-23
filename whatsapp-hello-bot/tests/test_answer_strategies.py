"""Live Ep answer path (calendar wins unless how-to merge)."""

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
from app.engines import engine1_legacy
from app.engines.base import ConversationContext

IMPORT_DIR = Path(__file__).resolve().parents[1] / "data" / "imports"
PHONE = "15550001111"


def _ctx(text: str) -> ConversationContext:
    return ConversationContext(
        phone_hash="hash",
        phone=PHONE,
        message_id="m",
        text=text,
        extras={},
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
    monkeypatch.setattr("app.faq_service.answer_faq_detailed", _fake_faq)
    monkeypatch.setattr("app.eval_framework.strategy_ep.answer_faq_detailed", _fake_faq)
    return engine1_legacy.LegacyEngine()


def test_ep_calendar_wins_on_ptsa_meeting(engine):
    out = engine.answer(_ctx("when is the next crone ptsa meeting"))
    assert out.answer_strategy == "Ep"
    assert out.route == "calendar"
    assert "Jan 14, 2027" in out.messages[0]
    assert "CronePTSA.org" not in out.messages[0]


def test_ep_still_merges_how_to_register(engine):
    out = engine.answer(_ctx("how do I register for the color run"))
    assert out.answer_strategy == "Ep"
    assert out.route == "calendar_faq"
    assert "FAQ ANSWER" in out.messages[0]
