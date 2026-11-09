import os

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""
os.environ["GUIDED_ENABLED"] = "true"
os.environ["OPENAI_API_KEY"] = ""

from app.engine_config import set_selected_engine_id
from app.engines.base import ENGINE_1, ENGINE_2
from app.engines.pipeline import process_message
from app.engines.registry import list_engines
from app.guided_state import clear_session


def test_engines_registered():
    engines = {e["id"]: e for e in list_engines()}
    assert engines[ENGINE_1]["implemented"] is True
    assert engines[ENGINE_2]["implemented"] is True
    assert engines["engine3_reserved"]["implemented"] is False
    assert engines["engine4_reserved"]["selectable"] is False


def test_engine1_direct_faq(tmp_path, monkeypatch):
    monkeypatch.setattr("app.guided_state.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.engine_config.CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.setattr("app.engine_config.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.observability.analytics_store.EVENTS_FILE", tmp_path / "e.jsonl")
    monkeypatch.setattr("app.observability.analytics_store.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.observability.tracing.TRACES_FILE", tmp_path / "t.jsonl")
    monkeypatch.setattr("app.observability.tracing.FAQ_GCS_BUCKET", "")
    set_selected_engine_id(ENGINE_1)
    clear_session("15550009999")
    result = process_message(
        phone="15550009999",
        text="Where is Lost & Found at Crone?",
        message_id="m1",
    )
    assert result.route == "faq"
    assert result.engine_id in {ENGINE_1, ENGINE_2}
    assert "cafeteria" in "\n".join(result.messages).lower()


def test_engine2_skips_checked_lost_found(tmp_path, monkeypatch):
    monkeypatch.setattr("app.guided_state.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.guided_metrics.METRICS_FILE", tmp_path / "gm.json")
    monkeypatch.setattr("app.guided_metrics.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.engine_config.CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.setattr("app.observability.analytics_store.EVENTS_FILE", tmp_path / "e.jsonl")
    monkeypatch.setattr("app.observability.tracing.TRACES_FILE", tmp_path / "t.jsonl")
    set_selected_engine_id(ENGINE_2)
    clear_session("15550008888")
    result = process_message(
        phone="15550008888",
        text="My daughter lost her PE shirt. She already checked both places.",
        message_id="m2",
    )
    assert result.engine_id == ENGINE_2
    assert result.route in {"guided_start", "guided_continue"}
    joined = "\n".join(result.messages).lower()
    assert "office" in joined or "did this help" in joined
