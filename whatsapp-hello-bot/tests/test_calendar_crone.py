import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""

import pytest

from app import calendar_service as svc
from app import calendar_store

IMPORT_DIR = Path(__file__).resolve().parents[1] / "data" / "imports"
D204_CSV = IMPORT_DIR / "school_district_204_2026_2027_calendar.csv"
CRONE_CSV = IMPORT_DIR / "crone_2026_2027_calendar.csv"
CRONE_URL = "https://docs.google.com/document/d/10WRr9ZPPmZiDH_a_2kz40TycyVIJ9eCGlIBAFL7hLIM/edit?tab=t.0"
D204_PDF = "SchoolCalendar2026-2027FINAL.pdf"
TODAY = date(2026, 11, 13)


def _fresh_store(tmp_path, monkeypatch):
    monkeypatch.setattr(calendar_store, "CALENDAR_FILE", tmp_path / "calendar.json")
    monkeypatch.setattr(calendar_store, "FAQ_GCS_BUCKET", "")
    calendar_store.clear_calendar_cache()


@pytest.fixture
def d204_only(tmp_path, monkeypatch):
    _fresh_store(tmp_path, monkeypatch)
    calendar_store.import_calendar_csv_text(D204_CSV.read_text(encoding="utf-8-sig"))
    yield
    calendar_store.clear_calendar_cache()


@pytest.fixture
def both(tmp_path, monkeypatch):
    _fresh_store(tmp_path, monkeypatch)
    calendar_store.import_calendar_csv_text(D204_CSV.read_text(encoding="utf-8-sig"))
    calendar_store.import_calendar_csv_text(CRONE_CSV.read_text(encoding="utf-8-sig"))
    yield
    calendar_store.clear_calendar_cache()


def _ask(question: str, today: date = TODAY) -> dict:
    assert svc.looks_like_calendar_question(question) is True, question
    result = svc.answer_calendar_question(question, today=today)
    assert result["handled"] is True, question
    return result


# --- A1: import ---------------------------------------------------------------


def test_crone_import_adds_27_events_and_keeps_district_meta(both):
    meta = calendar_store.get_calendar_meta()
    assert meta["event_count"] == 18 + 27
    assert "District 204" in meta["source_name"]
    assert D204_PDF in meta["source_url"]


def test_crone_import_is_idempotent(both):
    again = calendar_store.import_calendar_csv_text(CRONE_CSV.read_text(encoding="utf-8-sig"))
    assert again["imported"] == 27
    assert again["total"] == 45


def test_crone_conferences_do_not_overwrite_district_rows(both):
    events = calendar_store.list_events()
    nov2 = [e for e in events if e["start_date"] == "2026-11-02"]
    assert len(nov2) == 2
    district = [e for e in nov2 if D204_PDF in e["source_url"]]
    assert district and district[0]["student_attendance"] == "No School"


def test_crone_rows_never_change_school_day_answers(tmp_path, monkeypatch):
    _fresh_store(tmp_path, monkeypatch)
    calendar_store.import_calendar_csv_text(D204_CSV.read_text(encoding="utf-8-sig"))
    days = [date(2026, 10, 22), date(2026, 11, 2), date(2026, 9, 10), date(2027, 3, 15), date(2027, 5, 28)]
    before = [svc.is_school_day(d) for d in days]
    calendar_store.import_calendar_csv_text(CRONE_CSV.read_text(encoding="utf-8-sig"))
    assert [svc.is_school_day(d) for d in days] == before
    calendar_store.clear_calendar_cache()


# --- A2: per-event source footer ---------------------------------------------


def test_crone_event_cites_crone_doc(both):
    answer = _ask("when is the 6th grade social")["answer"]
    assert CRONE_URL in answer
    assert D204_PDF not in answer


def test_district_event_cites_district_pdf(both):
    answer = _ask("when is the institute day")["answer"]
    assert D204_PDF in answer
    assert CRONE_URL not in answer


def test_general_answer_keeps_calendar_wide_footer(both):
    answer = _ask("is there school on September 7, 2026?")["answer"]
    assert D204_PDF in answer
    assert CRONE_URL not in answer


def test_merged_conference_cites_both_sources_with_crone_time(both):
    result = _ask("when are the parent teacher conferences")
    answer = result["answer"]
    assert "Mar 15, 2027" in answer
    assert "12:00pm-7:30pm" in answer
    assert "no school" in answer.lower()
    assert CRONE_URL in answer and D204_PDF in answer
    assert answer.count("Parent/Teacher Conferences") == 1
    assert result["source_url"] == CRONE_URL


# --- A3: name lookup -----------------------------------------------------------


def test_next_ptsa_meeting_is_single_next_date(both):
    answer = _ask("when is the next PTSA meeting")["answer"]
    assert "Jan 14, 2027" in answer
    assert "10:30am" in answer
    assert "Nov 12" not in answer


def test_ptsa_meetings_list_upcoming_max_five(both):
    answer = _ask("when are the PTSA meetings")["answer"]
    assert answer.count("•") == 5
    assert "Jan 14, 2027" in answer and "May 13, 2027" in answer
    assert "Sep 10, 2026" not in answer


def test_past_event_is_marked_passed(both):
    answer = _ask("when is fall fest")["answer"]
    assert "Sep 1, 2026" in answer
    assert "already passed" in answer


def test_was_question_returns_most_recent_past(both):
    answer = _ask("when was the last ptsa meeting")["answer"]
    assert "Nov 12, 2026" in answer


def test_parent_teacher_without_slash_reaches_calendar(both):
    assert svc.looks_like_calendar_question("when are parent teacher conferences") is True


def test_month_in_question_narrows_dates(both):
    answer = _ask("when is the ptsa meeting in january")["answer"]
    assert "Jan 14, 2027" in answer
    assert "Feb 11" not in answer


def test_grade_number_picks_right_event(both):
    answer = _ask("when is the 6th grade social")["answer"]
    assert "Feb 19, 2027" in answer
    assert "7th Grade Social" not in answer


def test_institute_day_has_answer(both):
    answer = _ask("when is the institute day")["answer"]
    assert "Feb 26, 2027" in answer


def test_tentative_noted(both):
    answer = _ask("when is career night")["answer"]
    assert "Apr 28, 2027" in answer
    assert "Tentative" in answer


# --- A3: routing guard ----------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "how do I register for the color run",
        "how do I sign up to volunteer at fall fest",
        "how much does the 8th grade dance cost",
        "where is curriculum night",
        "can I buy tickets to the fine arts fest",
        "how do I register for parent teacher conferences",
    ],
)
def test_action_questions_skip_calendar(both, question):
    assert svc.looks_like_calendar_question(question) is False


@pytest.mark.parametrize(
    "question",
    [
        "when is the fall concert",
        "when is the book fair",
        "when is the fall break",
        "what is the ptsa",
        "ptsa meeting notes",
    ],
)
def test_unrelated_or_unmatched_questions_not_stolen(both, question):
    assert svc.looks_like_calendar_question(question) is False


# --- A4: first / last day --------------------------------------------------------


def test_first_day_of_school_from_crone(both):
    answer = _ask("when is the first day of school")["answer"]
    assert "Aug 17, 2026" in answer
    assert "8:00am" in answer
    assert CRONE_URL in answer


def test_last_day_of_school_from_crone_is_tentative(both):
    answer = _ask("when is the last day of school")["answer"]
    assert "May 28, 2027" in answer
    assert "Tentative" in answer
    assert CRONE_URL in answer


def test_first_day_falls_back_without_crone(d204_only):
    answer = _ask("when does school start")["answer"]
    assert "does not include a confirmed first day" in answer


# --- Engine routing -----------------------------------------------------------------


def _engine_ctx(text: str):
    from app.engines.base import ConversationContext

    return ConversationContext(
        phone_hash="hash", phone="15550001111", message_id="m1", text=text
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


def test_engine_answers_event_when_from_calendar_and_actions_from_faq(both, monkeypatch):
    from app.engines import engine1_legacy

    monkeypatch.setattr(engine1_legacy, "answer_faq_detailed", _fake_faq)
    engine = engine1_legacy.LegacyEngine()

    cal = engine.answer(_engine_ctx("when is the next PTSA meeting"))
    assert cal.route == "calendar"
    assert "Jan 14, 2027" in cal.messages[0]

    faq = engine.answer(_engine_ctx("how do I register for the color run"))
    assert faq.route == "faq"
