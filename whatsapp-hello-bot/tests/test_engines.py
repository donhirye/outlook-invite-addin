import os

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""
os.environ["GUIDED_ENABLED"] = "false"
os.environ["OPENAI_API_KEY"] = ""

from types import SimpleNamespace

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
    fake = lambda text: SimpleNamespace(
        answer="Crone has two Lost & Found locations: cafeteria and gym.",
        source_name="Test",
        source_url="",
        llm_invocations=0,
        faq_id="FAQ001",
        match_score=0.99,
        confidence=0.99,
        retrieval_mode="direct_qa",
        retrieved_chunks=[],
        input_tokens=None,
        output_tokens=None,
    )
    monkeypatch.setattr("app.faq_service.answer_faq_detailed", fake)
    monkeypatch.setattr("app.engines.engine1_legacy.answer_faq_detailed", fake)
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


def test_engine2_delegates_to_faq_not_guided(tmp_path, monkeypatch):
    monkeypatch.setattr("app.guided_state.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.engine_config.CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.setattr("app.observability.analytics_store.EVENTS_FILE", tmp_path / "e.jsonl")
    monkeypatch.setattr("app.observability.tracing.TRACES_FILE", tmp_path / "t.jsonl")
    fake = lambda text: SimpleNamespace(
        answer="Check Lost & Found in the cafeteria and outside the gym.",
        source_name="Test",
        source_url="",
        llm_invocations=0,
        faq_id="FAQ001",
        match_score=0.9,
        confidence=0.9,
        retrieval_mode="direct_qa",
        retrieved_chunks=[],
        input_tokens=None,
        output_tokens=None,
    )
    monkeypatch.setattr("app.faq_service.answer_faq_detailed", fake)
    monkeypatch.setattr("app.engines.engine1_legacy.answer_faq_detailed", fake)
    set_selected_engine_id(ENGINE_2)
    clear_session("15550008888")
    result = process_message(
        phone="15550008888",
        text="My daughter lost her PE shirt. She already checked both places.",
        message_id="m2",
    )
    assert result.engine_id == ENGINE_2
    assert result.route == "faq"
    assert "guided" not in (result.route or "")
