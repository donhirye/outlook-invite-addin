import os

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""

from app.event_link_store import (
    build_group_paste_message,
    build_wa_me_link,
    set_event_link_settings,
)


def test_build_wa_me_link_encodes_prefill():
    link = build_wa_me_link(
        "15552032022",
        "Hi, I have a question about Kendall 5th Grade Celebration",
    )
    assert link is not None
    assert link.startswith("https://wa.me/15552032022?text=")
    assert "Kendall" in link
    assert "%20" in link or "+" in link


def test_group_paste_message_matches_pinned_style(tmp_path, monkeypatch):
    path = tmp_path / "event_link.json"
    monkeypatch.setattr("app.event_link_store.EVENT_LINK_FILE", path)
    set_event_link_settings(
        bot_phone="15552032022",
        prefill_text="Hi, I have a question about Kendall 5th Grade Celebration",
    )
    msg = build_group_paste_message(
        "15552032022",
        "Hi, I have a question about Kendall 5th Grade Celebration",
    )
    assert msg is not None
    assert "🤖 Questions about Kendall 5th Grade Celebration?" in msg
    assert "Ask our Event Assistant anytime:" in msg
    assert "https://wa.me/15552032022?text=" in msg
