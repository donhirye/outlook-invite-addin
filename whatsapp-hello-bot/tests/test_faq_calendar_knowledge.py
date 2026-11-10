import os
from datetime import date
from pathlib import Path

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""

from app import calendar_service, calendar_store, faq_records


IMPORT_DIR = Path(__file__).resolve().parents[1] / "data" / "imports"
FAQ_CSV = IMPORT_DIR / "Crone_Combined_FAQs_Admin_Import.csv"
CAL_CSV = IMPORT_DIR / "school_district_204_2026_2027_calendar.csv"


def test_faq_csv_import_upserts_without_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(faq_records, "FAQ_RECORDS_FILE", tmp_path / "faq_records.json")
    monkeypatch.setattr(faq_records, "FAQ_GCS_BUCKET", "")
    faq_records.clear_faq_records_cache()
    monkeypatch.setattr(
        "app.faq_store.set_faq_text",
        lambda text, faq_path=None: text,
    )
    monkeypatch.setattr("app.faq_store.clear_faq_cache", lambda: None)

    text = FAQ_CSV.read_text(encoding="utf-8-sig")
    first = faq_records.import_faq_csv_text(text)
    second = faq_records.import_faq_csv_text(text)
    assert first["imported"] == 75
    assert second["imported"] == 75
    assert first["total"] == 75
    assert second["total"] == 75
    rec = faq_records.get_record("FAQ009")
    assert rec is not None
    assert "[DEMO ANSWER]" in rec["answer"]
    assert rec["source"]


def test_calendar_csv_import_and_thanksgiving(tmp_path, monkeypatch):
    monkeypatch.setattr(calendar_store, "CALENDAR_FILE", tmp_path / "calendar.json")
    monkeypatch.setattr(calendar_store, "FAQ_GCS_BUCKET", "")
    calendar_store.clear_calendar_cache()

    text = CAL_CSV.read_text(encoding="utf-8-sig")
    first = calendar_store.import_calendar_csv_text(text)
    second = calendar_store.import_calendar_csv_text(text)
    assert first["imported"] == 18
    assert second["total"] == 18

    result = calendar_service.answer_calendar_question(
        "When is Thanksgiving break?",
        today=date(2026, 11, 9),
    )
    assert result["handled"] is True
    assert "2026-11-23" in result["answer"]
    assert "2026-11-27" in result["answer"]
    assert "School District 204" in result["answer"] or "district" in result["answer"].lower()


def test_school_today_and_no_school(tmp_path, monkeypatch):
    monkeypatch.setattr(calendar_store, "CALENDAR_FILE", tmp_path / "calendar.json")
    monkeypatch.setattr(calendar_store, "FAQ_GCS_BUCKET", "")
    calendar_store.clear_calendar_cache()
    calendar_store.import_calendar_csv_text(CAL_CSV.read_text(encoding="utf-8-sig"))

    labor = calendar_service.answer_calendar_question(
        "Is there school on September 7, 2026?",
        today=date(2026, 9, 1),
    )
    assert labor["handled"] is True
    assert "No" in labor["answer"]

    spring = calendar_service.answer_calendar_question(
        "How many days until spring break?",
        today=date(2027, 3, 1),
    )
    assert spring["handled"] is True
    assert "days until" in spring["answer"].lower()


def test_december_january_time_off_uses_calendar(tmp_path, monkeypatch):
    monkeypatch.setattr(calendar_store, "CALENDAR_FILE", tmp_path / "calendar.json")
    monkeypatch.setattr(calendar_store, "FAQ_GCS_BUCKET", "")
    calendar_store.clear_calendar_cache()
    calendar_store.import_calendar_csv_text(CAL_CSV.read_text(encoding="utf-8-sig"))

    q = "is there time off for school during december/january?"
    assert calendar_service.looks_like_calendar_question(q) is True
    result = calendar_service.answer_calendar_question(q, today=date(2026, 11, 10))
    assert result["handled"] is True
    assert "Winter Break" in result["answer"]
    assert "2026-12-21" in result["answer"]
    assert "2027-01-01" in result["answer"]
    assert "School calendar" in result["answer"]


def test_holiday_season_phrasing_maps_to_winter_break(tmp_path, monkeypatch):
    monkeypatch.setattr(calendar_store, "CALENDAR_FILE", tmp_path / "calendar.json")
    monkeypatch.setattr(calendar_store, "FAQ_GCS_BUCKET", "")
    calendar_store.clear_calendar_cache()
    calendar_store.import_calendar_csv_text(CAL_CSV.read_text(encoding="utf-8-sig"))

    phrases = (
        "time off around the holidays",
        "do kids get a long break after Christmas",
        "any days off before New Year",
    )
    for q in phrases:
        assert calendar_service.looks_like_calendar_question(q) is True, q
        result = calendar_service.answer_calendar_question(q, today=date(2026, 11, 10))
        assert result["handled"] is True, q
        assert "Winter Break" in result["answer"], q
        assert "2026-12-21" in result["answer"], q
        assert "2027-01-01" in result["answer"], q
