import os

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""

from app.faq_admin import format_parent_answer, is_help_command


def test_is_help_command():
    assert is_help_command("/help")
    assert is_help_command("menu")
    assert not is_help_command("Where should I park?")


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
