import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""

import pytest

from app import calendar_picker as picker
from app import calendar_store, guided_state

IMPORT_DIR = Path(__file__).resolve().parents[1] / "data" / "imports"
D204_CSV = IMPORT_DIR / "school_district_204_2026_2027_calendar.csv"
CRONE_CSV = IMPORT_DIR / "crone_2026_2027_calendar.csv"
CRONE_URL = "docs.google.com/document/d/10WRr9ZPPmZiDH_a_2kz40TycyVIJ9eCGlIBAFL7hLIM"
D204_PDF = "SchoolCalendar2026-2027FINAL.pdf"
TODAY = date(2026, 11, 13)
PHONE = "15550001111"


def _setup(tmp_path, monkeypatch, *, crone: bool):
    monkeypatch.setattr(calendar_store, "CALENDAR_FILE", tmp_path / "calendar.json")
    monkeypatch.setattr(calendar_store, "FAQ_GCS_BUCKET", "")
    monkeypatch.setattr(guided_state, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(guided_state, "FAQ_GCS_BUCKET", "")
    monkeypatch.setattr(picker, "chicago_today", lambda: TODAY)
    calendar_store.clear_calendar_cache()
    calendar_store.import_calendar_csv_text(D204_CSV.read_text(encoding="utf-8-sig"))
    if crone:
        calendar_store.import_calendar_csv_text(CRONE_CSV.read_text(encoding="utf-8-sig"))


@pytest.fixture
def both(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, crone=True)
    yield
    calendar_store.clear_calendar_cache()


@pytest.fixture
def d204_only(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, crone=False)
    yield
    calendar_store.clear_calendar_cache()


# --- Detecting the question ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Show me the calendar",
        "show me the school calendar",
        "can I see the calendar?",
        "calendar",
        "school calendar",
        "what's on the calendar",
        "what calendars do you have",
        "send me the calendar please",
    ],
)
def test_show_calendar_questions_detected(text):
    assert picker.is_show_calendar_question(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "when is the next ptsa meeting",
        "how do I add the calendar to my phone",
        "send me the link to the school calendar",
        "show me the calendar for december",
        "is there school tomorrow",
        "where can I find the school calendar pdf",
        "how do I sign up for the calendar",
        "hello",
    ],
)
def test_other_questions_not_detected(text):
    assert picker.is_show_calendar_question(text) is False


# --- Asking ------------------------------------------------------------------------


def test_picker_asks_with_both_calendars_and_buttons(both):
    asked = picker.start_calendar_picker(PHONE, TODAY)
    body = asked["messages"][0]
    assert "SD 204 calendar" in body and "PTSA events calendar" in body and "Both" in body
    labels = [c["label"] for c in asked["choices"]]
    assert labels == ["SD 204 calendar", "PTSA events calendar", "Both"]
    assert all(len(label) <= 20 for label in labels)
    assert guided_state.get_session(f"calpick:{PHONE}") is not None


def test_single_calendar_lists_directly(d204_only):
    asked = picker.start_calendar_picker(PHONE, TODAY)
    assert asked["choices"] is None
    assert "Thanksgiving Break" in asked["messages"][0]
    assert guided_state.get_session(f"calpick:{PHONE}") is None


# --- Answering ---------------------------------------------------------------------


def _ask_then(reply: str):
    picker.start_calendar_picker(PHONE, TODAY)
    return picker.resolve_calendar_pick(PHONE, reply, TODAY)


@pytest.mark.parametrize("reply", ["1", "204", "district", "SD 204", "calpick:school-district-204-2026-2027-calendar", "the district one please"])
def test_pick_sd204(both, reply):
    result = _ask_then(reply)
    assert result is not None and len(result["messages"]) == 1
    msg = result["messages"][0]
    assert "Thanksgiving Break" in msg and "Winter Break" in msg
    assert D204_PDF in msg and CRONE_URL not in msg
    assert "General PTSA Meeting" not in msg


@pytest.mark.parametrize("reply", ["2", "ptsa", "PTSA events", "crone", "second", "the ptsa one"])
def test_pick_ptsa(both, reply):
    result = _ask_then(reply)
    assert result is not None and len(result["messages"]) == 1
    msg = result["messages"][0]
    assert "Jan 14, 2027" in msg and "Career Night" in msg
    assert CRONE_URL in msg and D204_PDF not in msg
    assert "Thanksgiving" not in msg


@pytest.mark.parametrize("reply", ["3", "both", "all", "calpick:both", "1 and 2", "204 and ptsa"])
def test_pick_both_sends_two_messages_with_own_sources(both, reply):
    result = _ask_then(reply)
    assert result is not None and len(result["messages"]) == 2
    first, second = result["messages"]
    assert D204_PDF in first and CRONE_URL not in first
    assert CRONE_URL in second and D204_PDF not in second


def test_lists_only_future_events(both):
    msg = _ask_then("2")["messages"][0]
    assert "Nov 12, 2026" not in msg  # PTSA meeting already held
    assert "Sep 10, 2026" not in msg
    assert "Jan 14, 2027" in msg
    dates = [line for line in msg.splitlines() if line.startswith("•")]
    assert len(dates) == 12  # 27 Crone events, 15 already past on Nov 13


def test_no_school_marked_and_ranges_shown(both):
    msg = _ask_then("1")["messages"][0]
    assert "Mon, Nov 23 – Fri, Nov 27, 2026: Thanksgiving Break — no school" in msg
    assert "Labor Day" not in msg


def test_unrelated_reply_drops_question(both):
    picker.start_calendar_picker(PHONE, TODAY)
    assert picker.resolve_calendar_pick(PHONE, "when is fall fest", TODAY) is None
    assert guided_state.get_session(f"calpick:{PHONE}") is None
    # A later "ptsa" is not treated as an answer any more.
    assert picker.resolve_calendar_pick(PHONE, "ptsa", TODAY) is None


def test_reply_naming_an_event_is_not_a_choice(both):
    picker.start_calendar_picker(PHONE, TODAY)
    assert picker.resolve_calendar_pick(PHONE, "ptsa meeting", TODAY) is None


def test_expired_question_is_dropped(both, monkeypatch):
    picker.start_calendar_picker(PHONE, TODAY)
    real = picker.time.time
    monkeypatch.setattr(picker.time, "time", lambda: real() + picker.PENDING_TTL_SECONDS + 5)
    assert picker.resolve_calendar_pick(PHONE, "1", TODAY) is None


def test_no_pending_question_means_no_answer(both):
    assert picker.resolve_calendar_pick(PHONE, "1", TODAY) is None


def test_long_list_is_capped(both, monkeypatch):
    monkeypatch.setattr(picker, "MAX_BODY_CHARS", 200)
    msg = _ask_then("2")["messages"][0]
    assert "more later in the year" in msg


# --- Through the engine ------------------------------------------------------------


def _ctx(text: str, message_type: str = "text"):
    from app.engines.base import ConversationContext

    return ConversationContext(
        phone_hash="hash", phone=PHONE, message_id="m", text=text, message_type=message_type
    )


def _fake_faq(text: str):
    return SimpleNamespace(
        answer="FAQ ANSWER",
        source_name="faq",
        source_url="https://example.com/faq",
        llm_invocations=0,
        faq_id="F1",
        match_score=0.9,
        confidence="high",
        retrieval_mode="direct",
    )


@pytest.fixture
def engine(both, monkeypatch):
    from app.engines import engine1_legacy

    monkeypatch.setattr(engine1_legacy, "answer_faq_detailed", _fake_faq)
    return engine1_legacy.LegacyEngine()


def test_engine_show_calendar_then_button_reply(engine):
    asked = engine.answer(_ctx("show me the calendar"))
    assert asked.route == "calendar"
    assert [c["label"] for c in asked.choices] == [
        "SD 204 calendar",
        "PTSA events calendar",
        "Both",
    ]
    answer = engine.answer(_ctx(asked.choices[1]["id"], "interactive"))
    assert answer.route == "calendar"
    assert "Jan 14, 2027" in answer.messages[0]


def test_engine_typed_both(engine):
    engine.answer(_ctx("Show me the calendar"))
    answer = engine.answer(_ctx("both"))
    assert len(answer.messages) == 2


def test_engine_unrelated_followup_answered_normally(engine):
    engine.answer(_ctx("show me the calendar"))
    answer = engine.answer(_ctx("when is the next PTSA meeting"))
    assert answer.route == "calendar"
    assert "Jan 14, 2027" in answer.messages[0]
    assert answer.choices is None
    # Question was dropped: "ptsa" alone now goes through the normal pipeline.
    follow = engine.answer(_ctx("ptsa"))
    assert "Upcoming dates" not in follow.messages[0]


def test_engine_how_to_add_calendar_goes_to_faq(engine):
    answer = engine.answer(_ctx("how do I add the calendar to my phone"))
    assert answer.route == "faq"
