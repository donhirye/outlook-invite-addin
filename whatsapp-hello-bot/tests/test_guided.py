import os

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""
os.environ["GUIDED_ENABLED"] = "true"

from app.guided_engine import advance, looks_like_direct_faq, preview_topic, start_topic
from app.guided_router import match_guided_topic, needs_human, route_message
from app.guided_state import already_seen_message, clear_session
from app.guided_store import get_topic, list_topics
from app.faq_store import get_faq_text


def test_faq_includes_demo_answers_and_categories():
    text = get_faq_text()
    assert "Where is Lost & Found at Crone?" in text
    assert "[DEMO ANSWER]" in text
    assert "## Clubs and Activities" in text
    assert text.count("Q:") >= 30


def test_lost_and_found_pack_loads():
    topic = get_topic("lost_and_found")
    assert topic is not None
    assert topic["enabled"] is True
    assert "identify_item" in topic["steps"]


def test_router_prefers_faq_for_where_is():
    clear_session("15550001111")
    decision = route_message("15550001111", "Where is Lost & Found?")
    assert decision["kind"] == "faq"


def test_router_table_examples():
    cases = [
        ("Where is Lost & Found?", "faq"),
        ("My daughter lost her jacket", "start_guided"),
        ("How much is a replacement ID?", "faq"),
        ("I lost my school ID", "start_guided"),
        ("When is picture retake day?", "faq"),
        ("I can't schedule conferences", "start_guided"),
        ("Where do I order a band polo?", "faq"),
        ("My spiritwear order is wrong", "start_guided"),
        ("Where is the Color Run link?", "faq"),
        ("I want to help with a PTSA event", "start_guided"),
    ]
    for idx, (message, expected) in enumerate(cases):
        phone = f"1555111{idx:04d}"
        clear_session(phone)
        decision = route_message(phone, message)
        assert decision["kind"] == expected, (message, decision)


def test_router_starts_lost_and_found_for_situation():
    clear_session("15550001112")
    decision = route_message("15550001112", "My daughter can't find her PE shirt")
    assert decision["kind"] == "start_guided"
    assert decision["topic_id"] == "lost_and_found"


def test_human_handoff_patterns():
    assert needs_human("Is Art Club worthwhile for my kid?")
    assert needs_human("I need to report a security issue")


def test_lost_and_found_clothing_branch(tmp_path, monkeypatch):
    phone = "15550002222"
    monkeypatch.setattr("app.guided_state.STATE_FILE", tmp_path / "guided_state.json")
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.guided_metrics.METRICS_FILE", tmp_path / "guided_metrics.json")
    monkeypatch.setattr("app.guided_metrics.FAQ_GCS_BUCKET", "")
    clear_session(phone)

    started = start_topic(phone, "lost_and_found")
    assert "What did your child lose?" in started["messages"][0]

    step2 = advance(phone, "1")
    assert "cafeteria" in step2["messages"][0].lower()

    step3 = advance(phone, "Not yet")
    assert any("check both locations" in m.lower() for m in step3["messages"])
    assert any("Did this help" in m for m in step3["messages"])

    done = advance(phone, "Yes, resolved")
    assert done["ended"] is True
    assert "Great! Glad I could help." in done["messages"][0]


def test_chromebook_branch_keeps_demo_tag(tmp_path, monkeypatch):
    phone = "15550003333"
    monkeypatch.setattr("app.guided_state.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.guided_metrics.METRICS_FILE", tmp_path / "metrics.json")
    monkeypatch.setattr("app.guided_metrics.FAQ_GCS_BUCKET", "")
    clear_session(phone)
    start_topic(phone, "lost_and_found")
    result = advance(phone, "Chromebook")
    assert any("[DEMO ANSWER]" in m for m in result["messages"])


def test_clubs_and_ptsa_packs_exist():
    assert get_topic("clubs") is not None
    assert get_topic("ptsa_events") is not None
    ids = {t["id"] for t in list_topics()}
    assert {"lost_and_found", "conferences", "spiritwear", "clubs", "ptsa_events"} <= ids


def test_ptsa_deadline_lookup(tmp_path, monkeypatch):
    phone = "15550005555"
    monkeypatch.setattr("app.guided_state.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.guided_metrics.METRICS_FILE", tmp_path / "metrics.json")
    monkeypatch.setattr("app.guided_metrics.FAQ_GCS_BUCKET", "")
    clear_session(phone)
    start_topic(phone, "ptsa_events")
    advance(phone, "Find an event deadline")
    result = advance(phone, "Color Run")
    assert any("[DEMO ANSWER]" in m for m in result["messages"])
    assert any("Did this help" in m for m in result["messages"])


def test_cancel_clears_session(tmp_path, monkeypatch):
    phone = "15550004444"
    monkeypatch.setattr("app.guided_state.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    clear_session(phone)
    start_topic(phone, "conferences")
    result = advance(phone, "cancel")
    assert result["ended"] is True


def test_message_dedupe(tmp_path, monkeypatch):
    monkeypatch.setattr("app.guided_state.SEEN_FILE", tmp_path / "seen.json")
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    assert already_seen_message("wamid.TEST1") is False
    assert already_seen_message("wamid.TEST1") is True


def test_preview_includes_resolution():
    lines = preview_topic("lost_and_found", ["1", "Not yet"])
    joined = "\n".join(lines)
    assert "Did this help you resolve your issue?" in joined


def test_direct_faq_detector():
    assert looks_like_direct_faq("Where is Lost & Found?")
    assert not looks_like_direct_faq("My daughter lost her jacket")
