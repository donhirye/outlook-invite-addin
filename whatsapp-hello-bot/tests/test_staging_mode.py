"""Staging mode vs production mode of the real app (fresh interpreter per case).

APP_ENV is read at import time, so each case runs ``app.main`` in a subprocess with
its own environment. Only read-only endpoints are exercised (no startup event, no
pipeline), so these tests never touch real data files.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STAGING_PASSWORD = "unit-test-staging-password"
STAGING_SECRET = "unit-test-staging-secret-key-0123456789"


def _run(code: str, **env: str) -> dict:
    base = {
        k: v
        for k, v in os.environ.items()
        if k not in {"APP_ENV", "WHATSAPP_ACCESS_TOKEN", "OPENAI_API_KEY"}
    }
    base.update(
        {
            "PYTHONPATH": str(ROOT),
            "FAQ_GCS_BUCKET": "",
            "ADMIN_PASSWORD": "changeme",
            "SECRET_KEY": "test-secret",
            "WHATSAPP_VERIFY_TOKEN": "my-verify-token",
        }
    )
    base.update(env)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=base,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


STAGING_ENV = {
    "APP_ENV": "staging",
    "ADMIN_PASSWORD": STAGING_PASSWORD,
    "SECRET_KEY": STAGING_SECRET,
}

STAGING_SCRIPT = f"""
import json
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app, follow_redirects=False)
out = {{}}
r = c.get("/admin"); out["login_status"] = r.status_code; out["login_banner"] = "STAGING ENVIRONMENT" in r.text
out["login_title"] = "[STAGING]" in r.text
out["webhook_post"] = c.post("/webhook", json={{"entry": []}}).status_code
out["webhook_get"] = c.get("/webhook", params={{"hub.mode": "subscribe", "hub.verify_token": "my-verify-token", "hub.challenge": "x"}}).status_code
out["docs"] = c.get("/docs").status_code
out["openapi"] = c.get("/openapi.json").status_code
out["metrics_anon"] = c.get("/metrics").status_code
out["chat_anon"] = c.get("/admin/test-chat").status_code
out["api_anon"] = c.post("/admin/test-chat/api/message", json={{"text": "hi"}}).status_code
out["reset_anon"] = c.post("/admin/test-chat/api/reset", json={{}}).status_code
bad = c.post("/admin/login", data={{"password": "wrong"}}); out["bad_login"] = bad.status_code
ok = c.post("/admin/login", data={{"password": "{STAGING_PASSWORD}"}}); out["good_login"] = ok.status_code
page = c.get("/admin/test-chat"); out["chat_page"] = page.status_code
out["chat_banner"] = "STAGING ENVIRONMENT" in page.text
out["chat_has_form"] = "chat-form" in page.text
link = c.get("/admin/link"); out["link_status"] = link.status_code
out["link_banner"] = "STAGING ENVIRONMENT" in link.text
out["link_has_chat_nav"] = 'href="/admin/test-chat"' in link.text
out["metrics_authed"] = c.get("/metrics").status_code
out["personas"] = c.get("/admin/test-chat/api/personas").json()["personas"][0]["id"]
print(json.dumps(out))
"""

PRODUCTION_SCRIPT = """
import json
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app, follow_redirects=False)
out = {}
out["admin_banner"] = "STAGING" in c.get("/admin").text
out["chat_page"] = c.get("/admin/test-chat").status_code
out["api_message"] = c.post("/admin/test-chat/api/message", json={"text": "hi"}).status_code
out["api_reset"] = c.post("/admin/test-chat/api/reset", json={}).status_code
out["api_personas"] = c.get("/admin/test-chat/api/personas").status_code
out["docs"] = c.get("/docs").status_code
out["webhook_verify"] = c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "my-verify-token", "hub.challenge": "abc"}).status_code
out["routes"] = sorted(r.path for r in app.routes if "test-chat" in getattr(r, "path", ""))
c.post("/admin/login", data={"password": "changeme"})
out["chat_page_logged_in"] = c.get("/admin/test-chat").status_code
out["api_logged_in"] = c.post("/admin/test-chat/api/message", json={"text": "hi"}).status_code
print(json.dumps(out))
"""


def test_staging_mode_end_to_end():
    out = _run(STAGING_SCRIPT, **STAGING_ENV)
    assert out["login_status"] == 200
    assert out["login_banner"] is True and out["login_title"] is True
    # Meta traffic is never processed in staging.
    assert out["webhook_post"] == 404 and out["webhook_get"] == 404
    # No unauthenticated API docs or counters.
    assert out["docs"] == 404 and out["openapi"] == 404
    assert out["metrics_anon"] == 401 and out["metrics_authed"] == 200
    # Everything new is behind login.
    assert out["chat_anon"] == 303
    assert out["api_anon"] == 401 and out["reset_anon"] == 401
    assert out["bad_login"] == 401 and out["good_login"] == 303
    assert out["chat_page"] == 200 and out["chat_banner"] is True and out["chat_has_form"] is True
    # Existing admin pages get the banner and the Test Chat nav link.
    assert out["link_status"] == 200
    assert out["link_banner"] is True and out["link_has_chat_nav"] is True
    assert out["personas"] == "parent_a"


def test_production_mode_has_no_test_chat_and_no_banner():
    out = _run(PRODUCTION_SCRIPT)  # APP_ENV unset == production
    assert out["routes"] == []
    assert out["chat_page"] == 404
    assert out["api_message"] == 404 and out["api_reset"] == 404 and out["api_personas"] == 404
    # Even when logged in as admin, Test Chat does not exist in production.
    assert out["chat_page_logged_in"] == 404 and out["api_logged_in"] == 404
    assert out["admin_banner"] is False
    assert out["docs"] == 200
    assert out["webhook_verify"] == 200


@pytest.mark.parametrize("value", ["", "prod", "Production", "stagging", "true", "1"])
def test_unknown_app_env_is_treated_as_production(value):
    out = _run(PRODUCTION_SCRIPT, APP_ENV=value)
    assert out["routes"] == [] and out["chat_page"] == 404


def test_staging_refuses_to_start_with_unsafe_config():
    code = """
import asyncio, json
from app import main
try:
    asyncio.run(main.log_credential_status())
    print(json.dumps({"error": None}))
except RuntimeError as exc:
    print(json.dumps({"error": str(exc)}))
"""
    out = _run(code, APP_ENV="staging")  # default admin password + secret key
    assert "ADMIN_PASSWORD" in out["error"] and "SECRET_KEY" in out["error"]

    out = _run(code, APP_ENV="staging", WHATSAPP_ACCESS_TOKEN="EAAB-token", **{
        "ADMIN_PASSWORD": STAGING_PASSWORD,
        "SECRET_KEY": STAGING_SECRET,
    })
    assert "WHATSAPP_ACCESS_TOKEN" in out["error"]


def test_production_startup_check_is_a_noop():
    code = """
import json
from app import config
print(json.dumps({"problems": config.staging_config_problems(), "staging": config.IS_STAGING}))
"""
    out = _run(code)  # default password + key are fine (unchanged) in production
    assert out == {"problems": [], "staging": False}


def test_whatsapp_sends_are_blocked_in_staging(monkeypatch):
    import httpx

    from app import whatsapp

    monkeypatch.setattr(whatsapp, "IS_STAGING", True)
    monkeypatch.setattr(whatsapp, "WHATSAPP_ACCESS_TOKEN", "EAAB-real-looking-token")
    monkeypatch.setattr(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "123456")

    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("staging must never open a network connection")

    monkeypatch.setattr(httpx, "AsyncClient", Boom)

    for result in (
        asyncio.run(whatsapp.send_text_message("15550100001", "hi")),
        asyncio.run(whatsapp.send_choices("15550100001", "pick", [{"id": "a", "label": "A"}])),
        asyncio.run(whatsapp.send_choices("15550100001", "pick", [{"id": str(i), "label": str(i)} for i in range(5)])),
        asyncio.run(whatsapp.mark_as_read_with_typing("wamid.123")),
    ):
        assert result.get("skipped") is True
        assert result.get("reason") == "staging_sends_disabled"
