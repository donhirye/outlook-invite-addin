import os
from pathlib import Path

from fastapi.testclient import TestClient

# Ensure imports resolve when running from repo root or this folder.
os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")

from app.greeting_store import get_greeting, set_greeting
from app.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_webhook_verification():
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

    # Wrong password
    bad = client.post("/admin/login", data={"password": "nope"})
    assert bad.status_code == 401

    # Good password
    ok = client.post("/admin/login", data={"password": "changeme"}, follow_redirects=False)
    assert ok.status_code == 303

    saved = client.post(
        "/admin/message",
        data={"message": "hello from admin"},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert get_greeting() == "hello from admin"


def test_inbound_message_triggers_send(monkeypatch):
    sent = {}

    async def fake_send(to_phone: str, body: str):
        sent["to"] = to_phone
        sent["body"] = body
        return {"ok": True}

    monkeypatch.setattr("app.main.send_text_message", fake_send)
    monkeypatch.setattr("app.main.get_greeting", lambda: "hello, how are you")

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
                                    "id": "wamid.test",
                                    "timestamp": "1",
                                    "type": "text",
                                    "text": {"body": "hi"},
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
    assert sent == {"to": "15551234567", "body": "hello, how are you"}
