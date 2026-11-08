import os

os.environ["WHATSAPP_VERIFY_TOKEN"] = "learning-verify-token"

import exercise_02_app
from fastapi.testclient import TestClient

client = TestClient(exercise_02_app.app)


def setup_function():
    exercise_02_app.RECEIVED.clear()


def test_verify_ok():
    r = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "learning-verify-token",
            "hub.challenge": "12345",
        },
    )
    assert r.status_code == 200
    assert r.text == "12345"


def test_verify_bad_token():
    r = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "nope",
            "hub.challenge": "12345",
        },
    )
    assert r.status_code == 403


def test_receive_text_message():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "18122165774",
                                    "type": "text",
                                    "text": {"body": "Where should I park?"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    r = client.post("/webhook", json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert exercise_02_app.RECEIVED == [
        {"from": "18122165774", "body": "Where should I park?"}
    ]
