import os
from pathlib import Path

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ.setdefault("FAQ_ADMIN_PHONES", "15551234567")
os.environ["FAQ_GCS_BUCKET"] = ""

from app.faq_admin import (
    SOURCE_PLACEHOLDER,
    append_faq_entry,
    format_parent_answer,
    is_faq_admin,
    is_faq_command,
    is_help_command,
    is_opener_message,
    parse_faq_command,
)


def test_parse_faq_multiline():
    text = """/faq
Q: Can grandparents attend?
A: Yes. Please sign in at the gym entrance.
"""
    assert parse_faq_command(text) == (
        "Can grandparents attend?",
        "Yes. Please sign in at the gym entrance.",
        None,
    )


def test_parse_faq_one_line():
    text = "/faq Q: Where is parking? A: Lot C near the gym."
    assert parse_faq_command(text) == (
        "Where is parking?",
        "Lot C near the gym.",
        None,
    )


def test_parse_faq_with_source():
    text = """/faq
Q: When is the Springfield trip?
A: May 29–30, 2027.
Source: Crone PTSA Newsletter – Nov 2026
"""
    assert parse_faq_command(text) == (
        "When is the Springfield trip?",
        "May 29–30, 2027.",
        "Crone PTSA Newsletter – Nov 2026",
    )


def test_parse_faq_invalid():
    assert parse_faq_command("/faq hello") is None
    assert parse_faq_command("Where should I park?") is None


def test_is_commands():
    assert is_faq_command("/faq Q: a A: b")
    assert is_help_command("/help")
    assert not is_help_command("Where should I park?")


def test_opener_messages():
    assert is_opener_message("hi")
    assert is_opener_message(
        "Hi, I have a question about Kendall 5th Grade Celebration"
    )
    assert is_opener_message("question about Kendall 5th Grade Celebration")
    assert not is_opener_message("Where should I park?")
    assert not is_opener_message("What time does it start?")


def test_admin_phone_check(monkeypatch):
    monkeypatch.setattr("app.faq_admin.FAQ_ADMIN_PHONES", {"15551234567"})
    assert is_faq_admin("15551234567")
    assert is_faq_admin("+1 (555) 123-4567")
    assert not is_faq_admin("19999999999")


def test_format_parent_answer_adds_source_placeholder():
    out = format_parent_answer("Parents should park in Lot C.")
    assert "*FAQ answer*" in out
    assert "Lot C" in out
    assert "Source: Crone PTSA FAQ" in out


def test_format_parent_answer_uses_named_source_and_url():
    out = format_parent_answer(
        "Parents should park in Lot C.",
        source_name="Crone PTSA Newsletter – Nov 2026",
        source_url="https://example.com/newsletter",
    )
    assert "Source: Crone PTSA Newsletter – Nov 2026" in out
    assert "https://example.com/newsletter" in out


def test_format_parent_answer_skips_source_on_fallback():
    out = format_parent_answer("I couldn't find that information in the event FAQ.")
    assert "Source:" not in out


def test_format_parent_answer_strips_invented_source():
    out = format_parent_answer(
        "The trip is May 29–30, 2027.\n\nSource: Made Up By Model",
        source_name="Crone PTSA Newsletter – Nov 2026",
        source_url="https://example.com/newsletter",
    )
    assert "Made Up By Model" not in out
    assert "Source: Crone PTSA Newsletter – Nov 2026" in out
    assert "https://example.com/newsletter" in out


def test_append_faq_entry(tmp_path, monkeypatch):
    faq_file = tmp_path / "faq.txt"
    faq_file.write_text("Arrival:\nStudents arrive by 8:15 AM.\n", encoding="utf-8")
    monkeypatch.setattr("app.faq_admin.rebuild_index", lambda *args, **kwargs: {"chunks": []})
    msg = append_faq_entry(
        "Can grandparents attend?",
        "Yes. Sign in at the gym.",
        faq_path=faq_file,
    )
    content = faq_file.read_text(encoding="utf-8")
    assert "Q: Can grandparents attend?" in content
    assert "A: Yes. Sign in at the gym." in content
    assert "Saved to FAQ" in msg
