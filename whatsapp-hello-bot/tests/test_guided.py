import os

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""
os.environ["GUIDED_ENABLED"] = "true"

from app.guided_engine import advance, start_topic
from app.guided_router import match_guided_topic, needs_human, route_message
from app.guided_state import already_seen_message, clear_session, set_session
from app.guided_store import get_topic, list_topics


def test_lost_and_found_pack_loads():
    topic = get_topic("lost_and_found")
    assert topic is not None
    assert topic["enabled"] is True
    assert "identify_item" in topic["steps"]


def test_router_prefers_faq_for_where_is():
    clear_session("15550001111")
    decision = route_message("15550001111", "Where is Lost & Found?")
    assert decision["kind"] == "faq"


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
    state_file = tmp_path / "guided_state.json"
    metrics_file = tmp_path / "guided_metrics.json"
    monkeypatch.setattr("app.guided_state.STATE_FILE", state_file)
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.guided_metrics.METRICS_FILE", metrics_file)
    monkeypatch.setattr("app.guided_metrics.FAQ_GCS_BUCKET", "")
    clear_session(phone)

    started = start_topic(phone, "lost_and_found")
    assert "What did your child lose?" in started["messages"][0]
    assert started["choices"]

    step2 = advance(phone, "1")
    assert "cafeteria" in step2["messages"][0].lower()

    step3 = advance(phone, "Not yet")
    assert any("check both locations" in m.lower() for m in step3["messages"])
    assert any("Did this help" in m for m in step3["messages"])

    done = advance(phone, "Yes, resolved")
    assert done["ended"] is True
    assert "Glad" in done["messages"][0]


def test_student_id_branch(tmp_path, monkeypatch):
    phone = "15550003333"
    monkeypatch.setattr("app.guided_state.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.guided_metrics.METRICS_FILE", tmp_path / "metrics.json")
    monkeypatch.setattr("app.guided_metrics.FAQ_GCS_BUCKET", "")
    clear_session(phone)
    start_topic(phone, "lost_and_found")
    result = advance(phone, "Student ID")
    assert any("$5" in m for m in result["messages"])
    assert any("Did this help" in m for m in result["messages"])


def test_cancel_clears_session(tmp_path, monkeypatch):
    phone = "15550004444"
    monkeypatch.setattr("app.guided_state.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    clear_session(phone)
    start_topic(phone, "conferences")
    result = advance(phone, "cancel")
    assert result["ended"] is True
    assert route_message(phone, "hello again later")["kind"] in {"faq", "start_guided", "human"}


def test_message_dedupe(tmp_path, monkeypatch):
    monkeypatch.setattr("app.guided_state.SEEN_FILE", tmp_path / "seen.json")
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    assert already_seen_message("wamid.TEST1") is False
    assert already_seen_message("wamid.TEST1") is True


def test_match_spiritwear_and_conferences():
    assert match_guided_topic("Where do I buy the band polo?")["id"] == "spiritwear"
    assert match_guided_topic("ParentVUE isn't showing slots")["id"] == "conferences"


def test_list_topics_includes_three():
    ids = {t["id"] for t in list_topics()}
    assert {"lost_and_found", "conferences", "spiritwear"} <= ids
