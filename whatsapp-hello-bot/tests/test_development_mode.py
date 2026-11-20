"""Local DEV mode (APP_ENV=development) — isolated subprocess per case."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(code: str, **env: str) -> dict:
    base = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "APP_ENV",
            "WHATSAPP_ACCESS_TOKEN",
            "WHATSAPP_PHONE_NUMBER_ID",
            "OPENAI_API_KEY",
            "FAQ_GCS_BUCKET",
            "DOTENV_PATH",
            "ADMIN_PASSWORD",
            "SECRET_KEY",
        }
    }
    base.update(
        {
            "PYTHONPATH": str(ROOT),
            "FAQ_GCS_BUCKET": "",
            "ADMIN_PASSWORD": "dev-local-password",
            "SECRET_KEY": "dev-local-secret-key-at-least-32-chars!!",
            "WHATSAPP_VERIFY_TOKEN": "my-verify-token",
            "DOTENV_PATH": str(ROOT / ".env.development.example"),
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


DEV_SCRIPT = """
import json
from fastapi.testclient import TestClient
from app.main import app
from app import config
c = TestClient(app, follow_redirects=False)
out = {}
out["is_dev"] = config.IS_DEVELOPMENT
out["data_dir_endswith_dev"] = str(config.DATA_DIR).replace("\\\\", "/").endswith("/data/dev")
out["gcs"] = config.FAQ_GCS_BUCKET
r = c.get("/admin")
out["login_banner"] = "LOCAL DEV ENVIRONMENT" in r.text
out["login_title"] = "[LOCAL DEV]" in r.text
out["webhook"] = c.post("/webhook", json={"entry": []}).status_code
out["docs"] = c.get("/docs").status_code
out["chat_anon"] = c.get("/admin/test-chat").status_code
ok = c.post("/admin/login", data={"password": "dev-local-password"})
out["login"] = ok.status_code
page = c.get("/admin/test-chat")
out["chat_page"] = page.status_code
out["chat_banner"] = "LOCAL DEV ENVIRONMENT" in page.text
out["chat_has_form"] = "chat-form" in page.text
print(json.dumps(out))
"""


def test_development_mode_banner_test_chat_and_isolation():
    out = _run(DEV_SCRIPT, APP_ENV="development")
    assert out["is_dev"] is True
    assert out["data_dir_endswith_dev"] is True
    assert out["gcs"] == ""
    assert out["login_banner"] is True and out["login_title"] is True
    assert out["webhook"] == 404
    assert out["docs"] == 200  # DEV keeps docs for experimentation
    assert out["chat_anon"] == 303
    assert out["login"] == 303
    assert out["chat_page"] == 200 and out["chat_banner"] is True
    assert out["chat_has_form"] is True


def test_development_refuses_gcs_bucket(tmp_path):
    env_file = tmp_path / "env-dev-gcs"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=development",
                "ADMIN_PASSWORD=dev-local-password",
                "SECRET_KEY=dev-local-secret-key-at-least-32-chars!!",
                "WHATSAPP_VERIFY_TOKEN=my-verify-token",
                "FAQ_GCS_BUCKET=vi1234-whatsapp-faq",
                "OPENAI_API_KEY=",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    code = """
import asyncio, json
from app import main
try:
    asyncio.run(main.log_credential_status())
    print(json.dumps({"error": None}))
except RuntimeError as exc:
    print(json.dumps({"error": str(exc)}))
"""
    out = _run(
        code,
        APP_ENV="development",
        DOTENV_PATH=str(env_file),
    )
    assert out["error"] and "FAQ_GCS_BUCKET" in out["error"]


def test_development_scrubs_inherited_openai_and_whatsapp_before_dotenv():
    code = """
import json
from app import config
print(json.dumps({
    "openai": config.OPENAI_API_KEY,
    "wa": config.WHATSAPP_ACCESS_TOKEN,
    "phone": config.WHATSAPP_PHONE_NUMBER_ID,
    "gcs": config.FAQ_GCS_BUCKET,
    "env": config.APP_ENV,
}))
"""
    # Parent shell looks like production; DEV must not keep those values when
    # .env.development.example leaves them empty.
    out = _run(
        code,
        APP_ENV="development",
        OPENAI_API_KEY="sk-prod-should-be-cleared",
        WHATSAPP_ACCESS_TOKEN="EAAB-prod",
        WHATSAPP_PHONE_NUMBER_ID="999",
        FAQ_GCS_BUCKET="should-clear-then-empty-from-file",
    )
    assert out["env"] == "development"
    assert out["openai"] == ""
    assert out["wa"] == ""
    assert out["phone"] == ""
    assert out["gcs"] == ""


def test_whatsapp_sends_are_blocked_in_development(monkeypatch):
    import httpx

    from app import whatsapp

    monkeypatch.setattr(whatsapp, "IS_DEVELOPMENT", True)
    monkeypatch.setattr(whatsapp, "IS_STAGING", False)
    monkeypatch.setattr(whatsapp, "WHATSAPP_ACCESS_TOKEN", "EAAB-real-looking-token")
    monkeypatch.setattr(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "123456")

    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("DEV must never open a network connection to Meta")

    monkeypatch.setattr(httpx, "AsyncClient", Boom)

    for result in (
        asyncio.run(whatsapp.send_text_message("15550100001", "hi")),
        asyncio.run(
            whatsapp.send_choices("15550100001", "pick", [{"id": "a", "label": "A"}])
        ),
        asyncio.run(whatsapp.mark_as_read_with_typing("wamid.123")),
    ):
        assert result.get("skipped") is True
        assert result.get("reason") == "development_sends_disabled"
