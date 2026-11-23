"""Test Chat behavior on the shared pipeline (isolated data files, no network)."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from app import calendar_store, test_chat, whatsapp
from app.config import TEMPLATES_DIR
from app.engines import pipeline

IMPORT_DIR = Path(__file__).resolve().parents[1] / "data" / "imports"
AUTH = {"x-test-auth": "1"}
def _fake_faq(text: str, *args, allow_rag: bool = True, **kwargs):
    return SimpleNamespace(
        answer="FAQ ANSWER for: " + text,
        source_name="Test FAQ",
        source_url="https://example.com/faq",
        llm_invocations=1,
        faq_id="F-1",
        match_score=0.91,
        confidence=0.8,
        retrieval_mode="direct",
        retrieved_chunks=["Category: Test\nQ: " + text + "\nA: FAQ ANSWER for: " + text],
        input_tokens=321,
        output_tokens=45,
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.guided_state.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("app.guided_state.SEEN_FILE", tmp_path / "seen.json")
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.observability.analytics_store.EVENTS_FILE", tmp_path / "events.jsonl")
    monkeypatch.setattr("app.observability.tracing.TRACES_FILE", tmp_path / "traces.jsonl")
    monkeypatch.setattr("app.observability.tracing.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.engine_config.CONFIG_FILE", tmp_path / "engine_config.json")
    monkeypatch.setattr("app.faq_service.answer_faq_detailed", _fake_faq)
    monkeypatch.setattr(
        "app.eval_framework.strategy_ep.answer_faq_detailed", _fake_faq
    )
    monkeypatch.setattr(calendar_store, "CALENDAR_FILE", tmp_path / "calendar.json")
    monkeypatch.setattr(calendar_store, "FAQ_GCS_BUCKET", "")
    calendar_store.clear_calendar_cache()
    for name in (
        "school_district_204_2026_2027_calendar.csv",
        "crone_2026_2027_calendar.csv",
    ):
        calendar_store.import_calendar_csv_text((IMPORT_DIR / name).read_text("utf-8-sig"))
    test_chat._recent.clear()

    # Anything that would reach WhatsApp is a test failure.
    async def no_send(*a, **k):
        raise AssertionError("Test Chat must never send to WhatsApp")

    monkeypatch.setattr(whatsapp, "_post_whatsapp", no_send)

    app = FastAPI()
    test_chat.register_test_chat(
        app,
        is_logged_in=lambda request: request.headers.get("x-test-auth") == "1",
        templates=Jinja2Templates(directory=str(TEMPLATES_DIR)),
        branding=lambda: {"logo_url": "/l.png", "favicon_url": "/f.png"},
    )
    yield TestClient(app, follow_redirects=False)
    calendar_store.clear_calendar_cache()


def _say(client, text, persona="parent_a", message_type="text"):
    resp = client.post(
        "/admin/test-chat/api/message",
        json={"text": text, "persona": persona, "message_type": message_type},
        headers=AUTH,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_uses_the_exact_whatsapp_pipeline():
    # Same function object the webhook calls: no duplicate AI engine.
    from app import main  # noqa: F401  (imports the real webhook module)

    assert test_chat.process_message is pipeline.process_message
    assert main.process_message is pipeline.process_message


def test_requires_login_everywhere(client):
    assert client.get("/admin/test-chat").status_code == 303
    assert client.post("/admin/test-chat/api/message", json={"text": "hi"}).status_code == 401
    assert client.post("/admin/test-chat/api/reset", json={}).status_code == 401
    assert client.get("/admin/test-chat/api/personas").status_code == 401


def test_page_renders_when_logged_in(client):
    resp = client.get("/admin/test-chat", headers=AUTH)
    assert resp.status_code == 200
    assert "Test Chat" in resp.text and "Reset conversation" in resp.text
    assert "Parent A" in resp.text and "Parent C" in resp.text


def test_answer_with_latency_model_tokens_and_trace(client, tmp_path):
    data = _say(client, "what time does the book fair open")
    assert data["ok"] is True
    assert data["messages"] and "FAQ ANSWER" in data["messages"][0]
    assert data["route"] == "faq"
    assert data["faq_id"] == "F-1" and data["faq_match_score"] == 0.91
    assert data["retrieved_chunks"] and "FAQ ANSWER" in data["retrieved_chunks"][0]
    assert data["latency_ms"] is not None and data["latency_ms"] >= 0
    assert data["model"]["llm_invocations"] == 1
    assert data["model"]["input_tokens"] == 321 and data["model"]["output_tokens"] == 45
    assert data["tools"] == []
    assert data["trace_id"]
    # The trace is tagged so Test Chat traffic can be told apart from WhatsApp.
    trace = json.loads((tmp_path / "traces.jsonl").read_text().splitlines()[-1])
    assert trace["channel"] == "test_chat" and trace["trace_id"] == data["trace_id"]
    assert trace["input_tokens"] == 321


def test_no_phone_numbers_or_secrets_in_output(client):
    data = _say(client, "hello there, is the school open")
    blob = json.dumps(data)
    assert "15550100001" not in blob
    assert data["phone_hash"] and data["phone_hash"] != "15550100001"
    personas = client.get("/admin/test-chat/api/personas", headers=AUTH).json()["personas"]
    assert "15550100001" not in json.dumps(personas)


def test_show_calendar_uses_overview_not_picker(client):
    asked = _say(client, "show me the calendar")
    assert asked["route"] == "overview"
    assert asked["retrieval_mode"] == "overview"
    assert not asked.get("choices")
    assert "What's going on" in asked["messages"][0]


def test_validation_and_limits(client, monkeypatch):
    bad_persona = client.post(
        "/admin/test-chat/api/message", json={"text": "hi", "persona": "nobody"}, headers=AUTH
    )
    assert bad_persona.status_code == 400
    too_long = client.post(
        "/admin/test-chat/api/message",
        json={"text": "x" * (test_chat.MAX_TEXT_CHARS + 1)},
        headers=AUTH,
    )
    assert too_long.status_code == 400
    monkeypatch.setattr(test_chat, "MAX_MESSAGES_PER_HOUR", 2)
    assert client.post("/admin/test-chat/api/message", json={"text": "one"}, headers=AUTH).status_code == 200
    assert client.post("/admin/test-chat/api/message", json={"text": "two"}, headers=AUTH).status_code == 200
    assert client.post("/admin/test-chat/api/message", json={"text": "three"}, headers=AUTH).status_code == 429


def test_secrets_are_redacted_from_debug_output(monkeypatch):
    monkeypatch.setattr(test_chat, "OPENAI_API_KEY", "sk-proj-supersecretvalue123")
    monkeypatch.setattr(test_chat, "ADMIN_PASSWORD", "my-admin-password-xyz")
    text = (
        "401 Incorrect API key provided: sk-proj-supersecretvalue123. "
        "Also sk-abcdef123456 and my-admin-password-xyz"
    )
    cleaned = test_chat.redact(text)
    assert "supersecretvalue123" not in cleaned
    assert "abcdef123456" not in cleaned
    assert "my-admin-password-xyz" not in cleaned
    assert test_chat.redact(None) is None


# --- Evaluation runner against a staging endpoint -----------------------------------


def test_remote_eval_runner_scores_cases_through_test_chat(client, monkeypatch, tmp_path):
    from evals import run as eval_run

    remote = TestClient(client.app, headers=AUTH, follow_redirects=False)
    monkeypatch.setattr(eval_run, "_remote_client", lambda base_url: remote)
    cases = [
        {
            # Use a non-calendar FAQ prompt so this test does not depend on the
            # separate "picture retake day" calendar matching bugfix.
            "id": "c1", "category": "faq", "input": "Where should I park for the event?",
            "expected_route": "faq", "required_answer_facts": ["FAQ ANSWER"],
        },
        {
            "id": "c3", "category": "faq", "input": "Where is the cafeteria?",
            "expected_route": "faq", "required_answer_facts": ["a fact that is not there"],
        },
    ]
    row = eval_run.run_remote("https://staging.example", cases, max_llm_calls=100)
    assert row["cases_run"] == 2
    assert row["passed"] == 1 and row["failed"] == 1
    assert row["llm_calls"] == 2 and row["input_tokens"] == 642
    failed = [r for r in row["results"] if not r["passed"]]
    assert failed[0]["id"] == "c3" and "missing fact" in failed[0]["failures"][0]

    stopped = eval_run.run_remote("https://staging.example", cases, max_llm_calls=1)
    assert stopped["cases_run"] == 1  # spend guard stops the run early


def test_remote_eval_runner_refuses_a_service_without_test_chat(monkeypatch):
    import httpx

    from evals import run as eval_run

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/admin/login":
            return httpx.Response(303, headers={"location": "/admin/link"})
        return httpx.Response(404)  # what production answers for Test Chat

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setenv("STAGING_ADMIN_PASSWORD", "x")
    with pytest.raises(SystemExit) as exc:
        eval_run._remote_client("https://prod.example")
    assert "no Test Chat endpoint" in str(exc.value)


def test_remote_eval_requires_password_and_live_flag(monkeypatch):
    from evals import run as eval_run

    monkeypatch.delenv("STAGING_ADMIN_PASSWORD", raising=False)
    with pytest.raises(SystemExit):
        eval_run._remote_client("https://staging.example")


