"""Overview dual-source scan: per-date bullets, no loose related junk."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""

import pytest

from app import calendar_store
from app import overview_service as overview
from app.faq_records import clear_faq_records_cache, get_record, upsert_record

IMPORT_DIR = Path(__file__).resolve().parents[1] / "data" / "imports"
TODAY = date(2026, 11, 22)


@pytest.fixture
def dual(tmp_path, monkeypatch):
    monkeypatch.setattr(calendar_store, "CALENDAR_FILE", tmp_path / "calendar.json")
    monkeypatch.setattr(calendar_store, "FAQ_GCS_BUCKET", "")
    monkeypatch.setattr(overview, "chicago_today", lambda: TODAY)
    monkeypatch.setattr("app.faq_records.FAQ_RECORDS_FILE", tmp_path / "faq_records.json")
    monkeypatch.setattr("app.faq_records.FAQ_GCS_BUCKET", "")
    clear_faq_records_cache()
    calendar_store.clear_calendar_cache()
    calendar_store.import_calendar_csv_text(
        (IMPORT_DIR / "school_district_204_2026_2027_calendar.csv").read_text(
            encoding="utf-8-sig"
        )
    )
    calendar_store.import_calendar_csv_text(
        (IMPORT_DIR / "crone_2026_2027_calendar.csv").read_text(encoding="utf-8-sig")
    )
    upsert_record(
        {
            "faq_id": "SHIRT-ORDER",
            "category": "NVHS",
            "question": "When do Class of 2031 NVHS Wildcat shirt sales close?",
            "answer": (
                "Shirt sales for the Class of 2031 NVHS Wildcat shirt are open "
                "through December 15, 2026, so you need to place your order by that date."
            ),
            "source": "Crone PTSA Newsletter - 2026-11-11",
            "source_url": "https://example.com/shirts",
            "status": "Active",
        }
    )
    upsert_record(
        {
            "faq_id": "SHIRT-PICKUP",
            "category": "NVHS",
            "question": "When can I pick up Class of 2031 NVHS Wildcat shirts?",
            "answer": (
                "Ordered Class of 2031 NVHS Wildcat shirts will be available for pickup "
                "in the Wildcat Wear store during the Class of 2031 Wildcat Welcome on "
                "January 13, 2027."
            ),
            "source": "Crone's Weekly Newsletter - 2026-10-30",
            "status": "Active",
        }
    )
    upsert_record(
        {
            "faq_id": "SPRINGFIELD",
            "category": "Trips",
            "question": "When is the 7th Grade Springfield/St. Louis trip?",
            "answer": "The 7th Grade Springfield/St. Louis trip is May 29–30, 2027.",
            "source": "Crone PTSA Newsletter - 2026-09-16",
            "event_date": "2027-05-29",
            "status": "Active",
        }
    )
    upsert_record(
        {
            "faq_id": "HALLOWEEN",
            "category": "Social",
            "question": "When is the 7th Grade Social?",
            "answer": (
                "All Crone 7th graders are invited to the Halloween-themed 7th Grade "
                "Social on Friday, October 16, 2026, from 6:00 PM to 8:00 PM."
            ),
            "source": "Crone PTSA Newsletter",
            "status": "Active",
        }
    )
    upsert_record(
        {
            "faq_id": "BASKETBALL",
            "category": "Athletics",
            "question": "When are the upcoming Crone basketball games?",
            "answer": (
                "Upcoming basketball games are scheduled for Tuesday, November 10, 2026, "
                "against Jefferson for 7H and 8A; Thursday, November 12, against Granger; "
                "Tuesday, December 1, 2026, against Still; Thursday, December 3, 2026, "
                "against Lincoln; Monday, December 7, 2026, against Washington."
            ),
            "source": "Crone Weekly",
            "status": "Active",
        }
    )
    yield
    clear_faq_records_cache()
    calendar_store.clear_calendar_cache()


def test_overview_question_detection():
    assert overview.is_overview_question("what is going on in december?")
    assert overview.is_overview_question("show me all events in may 2027")
    assert overview.is_overview_question("whats happening in december?")
    assert overview.is_overview_question("whats ahppening in december?")  # typo
    assert not overview.is_overview_question("how do I register for band")
    assert not overview.is_overview_question("Where is Lost & Found?")


def test_december_per_date_bullets_no_loose_related(dual):
    result = overview.answer_overview(
        "what is going on in december? tell me all events",
        today=TODAY,
    )
    assert result is not None
    body = result["messages"][0]
    assert "2026-12-15" in body
    assert "deadline" in body.lower()
    # Shirt pickup linked explicitly
    assert "2027-01-13" in body
    assert "Related follow-up" in body
    # Basketball: only December game lines, not November blob as the bullet
    assert "2026-12-01" in body
    assert "2026-12-03" in body
    assert "2026-12-07" in body
    # November games must not appear as December bullets / past related junk
    assert "2026-11-10" not in body
    assert "2026-10-16" not in body
    assert "Halloween" not in body
    # One bullet per date style (shirt line is its own bullet)
    assert body.count("2026-12-15") == 1
    evidence = "\n".join(result["retrieved_chunks"])
    assert "SHIRT-ORDER" in evidence
    assert "SHIRT-PICKUP" in evidence or "2027-01-13" in evidence


def test_may_2027_overview_includes_springfield(dual):
    result = overview.answer_overview(
        "show me all events in may 2027?",
        today=TODAY,
    )
    assert result is not None
    evidence = "\n".join(result["retrieved_chunks"])
    assert "SPRINGFIELD" in evidence
    assert "SHIRT-ORDER" not in evidence
    assert "2026-12-15" not in result["messages"][0]


def test_sibling_topic_answer_merges_both_dates(dual):
    primary = get_record("SHIRT-ORDER")
    siblings = overview.find_sibling_records(primary)
    assert any(s.get("faq_id") == "SHIRT-PICKUP" for s in siblings)
    assert not any(s.get("faq_id") == "HALLOWEEN" for s in siblings)
    body, chunks = overview.format_sibling_topic_answer(primary, siblings)
    assert "2026-12-15" in body
    assert "2027-01-13" in body


def test_extract_dated_snippets_splits_multi_game_answer():
    text = (
        "Games: Tuesday, November 10, 2026, against Jefferson; "
        "Tuesday, December 1, 2026, against Still; "
        "Thursday, December 3, 2026, against Lincoln."
    )
    snips = overview.extract_dated_snippets(
        text,
        window_start=date(2026, 12, 1),
        window_end=date(2026, 12, 31),
    )
    dates = [s["date"] for s in snips]
    assert date(2026, 12, 1) in dates
    assert date(2026, 12, 3) in dates
    assert date(2026, 11, 10) not in dates
    assert "Still" in snips[0]["clause"] or "Still" in snips[1]["clause"]
