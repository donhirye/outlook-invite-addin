import pytest

from exercise_01 import (
    build_wa_me_link,
    is_help_command,
    is_opener_message,
    normalize_phone,
)


def test_normalize_phone():
    assert normalize_phone("+1 (812) 216-5774") == "18122165774"
    assert normalize_phone("abc") == ""


def test_is_help_command():
    assert is_help_command("Help") is True
    assert is_help_command("/menu") is True
    assert is_help_command("where is parking") is False


def test_is_opener_message():
    assert is_opener_message("") is True
    assert is_opener_message("hi") is True
    assert is_opener_message("Hi, I have a question about Kendall") is True
    assert is_opener_message("Where should I park?") is False


def test_build_wa_me_link():
    link = build_wa_me_link(
        "15552032022",
        "Hi, I have a question about Kendall 5th Grade Celebration",
    )
    assert link is not None
    assert link.startswith("https://wa.me/15552032022?text=")
    assert "Kendall" in link
    assert build_wa_me_link("", "hello") is None
