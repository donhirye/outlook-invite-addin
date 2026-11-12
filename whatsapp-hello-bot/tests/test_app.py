import os

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")

from fastapi.testclient import TestClient

from app.greeting_store import get_greeting, set_greeting
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_webhook_verification(monkeypatch):
    monkeypatch.setattr("app.main.WHATSAPP_VERIFY_TOKEN", "my-verify-token")
    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "my-verify-token",
            "hub.challenge": "12345",
        },
    )
    assert response.status_code == 200
    assert response.text == "12345"


def test_webhook_verification_rejects_bad_token():
    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "12345",
        },
    )
    assert response.status_code == 403


def test_greeting_store_roundtrip(tmp_path, monkeypatch):
    greeting_file = tmp_path / "greeting.json"
    monkeypatch.setattr("app.greeting_store.GREETING_FILE", greeting_file)
    set_greeting("hello, how are you")
    assert get_greeting() == "hello, how are you"


def test_admin_login_and_save_greeting(tmp_path, monkeypatch):
    greeting_file = tmp_path / "greeting.json"
    monkeypatch.setattr("app.greeting_store.GREETING_FILE", greeting_file)
    monkeypatch.setattr("app.main.get_greeting", get_greeting)
    monkeypatch.setattr("app.main.set_greeting", set_greeting)

    bad = client.post("/admin/login", data={"password": "nope"})
    assert bad.status_code == 401

    ok = client.post("/admin/login", data={"password": "changeme"}, follow_redirects=False)
    assert ok.status_code == 303
    assert ok.headers["location"] == "/admin/link"

    saved = client.post(
        "/admin/intro",
        data={"message": "hello from admin"},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert get_greeting() == "hello from admin"


def test_inbound_message_triggers_faq_reply(monkeypatch, tmp_path):
    sent = {}
    metrics_file = tmp_path / "usage_metrics.json"

    async def fake_send(to_phone: str, body: str, choices=None):
        sent["to"] = to_phone
        sent["body"] = body
        return {"ok": True}

    typing = {}

    async def fake_typing(message_id: str):
        typing["message_id"] = message_id
        return {"success": True}

    monkeypatch.setattr("app.main.send_text_message", fake_send)
    monkeypatch.setattr("app.main.send_choices", fake_send)
    monkeypatch.setattr("app.main.mark_as_read_with_typing", fake_typing)
    from app.faq_service import FaqAnswer

    def _fake_faq(question, faq_path=None):
        return FaqAnswer(
            answer="Parents should park in Lot C.",
            confidence=0.95,
            match_score=0.2,
            retrieval_mode="rag",
            llm_invocations=1,
        )

    monkeypatch.setattr("app.engines.engine1_legacy.answer_faq_detailed", _fake_faq)
    monkeypatch.setattr("app.faq_service.answer_faq_detailed", _fake_faq)
    monkeypatch.setattr("app.metrics.METRICS_FILE", metrics_file)
    monkeypatch.setattr("app.guided_state.SEEN_FILE", tmp_path / "seen.json")
    monkeypatch.setattr("app.guided_state.STATE_FILE", tmp_path / "guided_state.json")
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.observability.analytics_store.EVENTS_FILE", tmp_path / "events.jsonl")
    monkeypatch.setattr("app.observability.tracing.TRACES_FILE", tmp_path / "traces.jsonl")
    monkeypatch.setattr("app.engine_config.CONFIG_FILE", tmp_path / "engine_config.json")

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "15559876543",
                                    "id": "wamid.test",
                                    "timestamp": "1",
                                    "type": "text",
                                    "text": {"body": "Where should I park?"},
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }
    response = client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert typing["message_id"] == "wamid.test"
    assert sent["to"] == "15559876543"
    assert "Parents should park in Lot C." in sent["body"]
    assert sent["body"].startswith("*FAQ answer*")
    metrics = client.get("/metrics").json()
    assert metrics["questions_asked"] >= 1
    assert metrics["unique_users"] >= 1


def test_inbound_faq_admin_command(monkeypatch, tmp_path):
    sent = {}
    metrics_file = tmp_path / "usage_metrics.json"
    faq_file = tmp_path / "faq.txt"
    faq_file.write_text("Arrival:\n8:15 AM\n", encoding="utf-8")

    async def fake_send(to_phone: str, body: str, choices=None):
        sent["to"] = to_phone
        sent["body"] = body
        return {"ok": True}

    def fake_get(faq_path=None):
        return faq_file.read_text(encoding="utf-8").strip()

    def fake_set(text, faq_path=None):
        cleaned = text.strip()
        faq_file.write_text(cleaned + "\n", encoding="utf-8")
        return cleaned

    async def fake_typing(message_id: str):
        return {"success": True}

    monkeypatch.setattr("app.main.send_text_message", fake_send)
    monkeypatch.setattr("app.main.send_choices", fake_send)
    monkeypatch.setattr("app.main.mark_as_read_with_typing", fake_typing)
    monkeypatch.setattr("app.metrics.METRICS_FILE", metrics_file)
    monkeypatch.setattr("app.faq_admin.get_faq_text", fake_get)
    monkeypatch.setattr("app.faq_admin.set_faq_text", fake_set)
    monkeypatch.setattr("app.faq_admin.rebuild_index", lambda *a, **k: {"chunks": []})
    monkeypatch.setattr("app.faq_admin.FAQ_ADMIN_PHONES", {"15551234567"})
    monkeypatch.setattr("app.guided_state.SEEN_FILE", tmp_path / "seen_admin.json")
    monkeypatch.setattr("app.guided_state.STATE_FILE", tmp_path / "guided_state_admin.json")
    monkeypatch.setattr("app.guided_state.FAQ_GCS_BUCKET", "")
    monkeypatch.setattr("app.observability.analytics_store.EVENTS_FILE", tmp_path / "events.jsonl")
    monkeypatch.setattr("app.observability.tracing.TRACES_FILE", tmp_path / "traces.jsonl")
    monkeypatch.setattr("app.engine_config.CONFIG_FILE", tmp_path / "engine_config.json")

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "15551234567",
                                    "id": "wamid.admin",
                                    "timestamp": "1",
                                    "type": "text",
                                    "text": {
                                        "body": (
                                            "/faq Q: Can grandparents attend? "
                                            "A: Yes. Sign in at the gym."
                                        )
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }
    response = client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert sent["to"] == "15551234567"
    assert "Saved to FAQ" in sent["body"]
    assert "Can grandparents attend?" in faq_file.read_text(encoding="utf-8")


def test_admin_faq_ui_roundtrip(tmp_path, monkeypatch):
    records_file = tmp_path / "faq_records.json"
    monkeypatch.setattr("app.faq_records.FAQ_RECORDS_FILE", records_file)
    monkeypatch.setattr("app.faq_records.FAQ_GCS_BUCKET", "")
    from app.faq_records import clear_faq_records_cache, list_records

    clear_faq_records_cache()
    monkeypatch.setattr(
        "app.faq_store.set_faq_text",
        lambda text, faq_path=None: text,
    )
    monkeypatch.setattr("app.faq_store.clear_faq_cache", lambda: None)
    monkeypatch.setattr("app.main.ensure_faq_records_seeded", lambda: {"seeded": False, "total": 0})

    client.get("/admin/logout")
    denied = client.get("/admin/faq", follow_redirects=False)
    assert denied.status_code == 303

    client.post("/admin/login", data={"password": "changeme"}, follow_redirects=False)
    page = client.get("/admin/faq")
    assert page.status_code == 200
    assert "CSV import" in page.text
    assert "Group link" in page.text
    assert "Intro" in page.text
    assert 'href="/admin/faq"' in page.text
    assert 'href="/admin/calendar"' in page.text

    csv_body = (
        "FAQ_ID,Category,Question,Answer,Source,Source_URL,Published_Date,Event_Date,Status\n"
        "FAQ999,Events,When is Kendall Celebration?,Friday 2pm,PTSA,,2026-01-01,,Active\n"
    )
    saved = client.post(
        "/admin/faq/import",
        files={"csv_file": ("faqs.csv", csv_body, "text/csv")},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    clear_faq_records_cache()
    recs = list_records(include_inactive=True)
    assert any(r.get("faq_id") == "FAQ999" for r in recs)


def test_admin_link_page_generates_copy_message(tmp_path, monkeypatch):
    link_file = tmp_path / "event_link.json"
    monkeypatch.setattr("app.event_link_store.EVENT_LINK_FILE", link_file)
    monkeypatch.setattr("app.event_link_store.FAQ_GCS_BUCKET", "")

    client.get("/admin/logout")
    client.post("/admin/login", data={"password": "changeme"}, follow_redirects=False)

    saved = client.post(
        "/admin/link",
        data={
            "bot_phone": "15552032022",
            "prefill_text": "Hi, I have a question about Kendall 5th Grade Celebration",
            "group_message": (
                "Custom pin text for parents\n"
                "https://wa.me/15552032022?text=old"
            ),
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303

    page = client.get("/admin/link")
    assert page.status_code == 200
    assert "Group message to pin" in page.text
    assert "Custom pin text for parents" in page.text
    assert "https://wa.me/15552032022?text=" in page.text
    assert "Kendall 5th Grade Celebration" in page.text
    assert "/static/branding/crone-ptsa-assistant-pin.png" in page.text
    assert "/static/branding/crone_logo.png" in page.text

    poster = client.get("/static/branding/crone-ptsa-assistant-pin.png")
    assert poster.status_code == 200
    assert poster.headers["content-type"].startswith("image/")


def test_admin_guided_page_lists_topics():
    client.get("/admin/logout")
    client.post("/admin/login", data={"password": "changeme"}, follow_redirects=False)
    page = client.get("/admin/guided")
    assert page.status_code == 200
    assert "Guided topics" in page.text
    assert "lost_and_found" in page.text
    assert "Resolution metrics" in page.text
    assert 'href="/admin/guided"' in page.text
