"""Releases dashboard — routes + helpers (no Cloud writes in unit tests)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

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
            "GIT_SHA",
            "STAGING_BASE_URL",
            "PRODUCTION_BASE_URL",
            "GITHUB_TOKEN",
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
            "GIT_SHA": "abc1234deadbeef",
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


def test_health_includes_app_env_and_git_sha():
    out = _run(
        """
import json
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
r = c.get("/health")
print(json.dumps({"status": r.status_code, "body": r.json()}))
""",
        APP_ENV="development",
        GIT_SHA="abc1234deadbeef",
    )
    assert out["status"] == 200
    assert out["body"]["status"] == "ok"
    assert out["body"]["app_env"] == "development"
    assert out["body"]["git_sha"] == "abc1234deadbeef"


def test_releases_available_in_development_and_staging_not_production():
    dev = _run(
        """
import json
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app, follow_redirects=False)
anon = c.get("/admin/releases")
login = c.post("/admin/login", data={"password": "dev-local-password"})
page = c.get("/admin/releases")
print(json.dumps({
  "anon": anon.status_code,
  "login": login.status_code,
  "page": page.status_code,
  "has_tracker": "Experiment" in page.text and "release tracker" in page.text.lower(),
  "has_staging_card": "STAGING" in page.text,
  "has_prod_card": "PRODUCTION" in page.text,
  "no_local_dev_card": "Local DEV environment" not in page.text or "Parked" in page.text,
  "no_deploy_button": "Deploy to" not in page.text,
  "has_refresh": "/admin/releases/refresh" in page.text,
  "has_decision_form": "/admin/releases/decision" in page.text,
}))
""",
        APP_ENV="development",
    )
    assert dev["anon"] in {302, 303}
    assert dev["page"] == 200
    assert dev["has_tracker"] is True
    assert dev["has_staging_card"] is True
    assert dev["has_prod_card"] is True
    assert dev["no_deploy_button"] is True
    assert dev["has_refresh"] is True
    assert dev["has_decision_form"] is True

    staging = _run(
        """
import json
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app, follow_redirects=False)
anon = c.get("/admin/releases")
login = c.post("/admin/login", data={"password": "unit-test-staging-password"})
page = c.get("/admin/releases")
print(json.dumps({
  "anon": anon.status_code,
  "page": page.status_code,
  "has_tracker": "release tracker" in page.text.lower(),
}))
""",
        APP_ENV="staging",
        ADMIN_PASSWORD="unit-test-staging-password",
        SECRET_KEY="unit-test-staging-secret-key-0123456789",
        DOTENV_PATH="",
    )
    assert staging["anon"] in {302, 303}
    assert staging["page"] == 200
    assert staging["has_tracker"] is True

    prod = _run(
        """
import json
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app, follow_redirects=False)
r = c.get("/admin/releases")
print(json.dumps({"status": r.status_code}))
""",
        APP_ENV="production",
        DOTENV_PATH="",
        ADMIN_PASSWORD="changeme",
        SECRET_KEY="test-secret",
    )
    assert prod["status"] == 404


def test_registry_decisions_and_history(tmp_path, monkeypatch):
    from app.releases import registry

    reg = tmp_path / "experiments.json"
    reg.write_text(
        json.dumps(
            {
                "experiments": [
                    {
                        "id": "x",
                        "name": "Demo",
                        "objective": "Try things",
                        "branch": "feature/demo",
                        "decision": "testing",
                    }
                ],
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(registry, "REGISTRY_PATH", reg)
    monkeypatch.setattr(registry, "FAQ_GCS_BUCKET", "")
    items = registry.load_experiments()
    assert items[0]["decision"] == "testing"
    assert items[0]["decision_label"] == "Testing"

    out = registry.record_decision(
        experiment_id="x",
        decision="accepted",
        reason="Looks good",
        commit_id="abc1234",
    )
    assert out["ok"] is True
    updated = registry.load_experiments()[0]
    assert updated["decision"] == "accepted"
    assert updated["reason"] == "Looks good"
    doc = json.loads(reg.read_text(encoding="utf-8"))
    assert doc["history"][-1]["from"] == "testing"
    assert doc["history"][-1]["to"] == "accepted"


def test_registry_migrates_legacy_status(tmp_path, monkeypatch):
    from app.releases import registry

    reg = tmp_path / "experiments.json"
    reg.write_text(
        json.dumps(
            {
                "experiments": [
                    {
                        "id": "old",
                        "name": "Old",
                        "objective": "legacy",
                        "branch": "feature/old",
                        "status": "experimental",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(registry, "REGISTRY_PATH", reg)
    monkeypatch.setattr(registry, "FAQ_GCS_BUCKET", "")
    assert registry.load_experiments()[0]["decision"] == "testing"


def test_live_probe_handles_missing_url_and_http(monkeypatch):
    from app.releases import live

    missing = live.probe_health("")
    assert missing["status"] == "Not Verified"

    class FakeResp:
        status = 200

        def read(self):
            return b'{"status":"ok","app_env":"staging","git_sha":"deadbeef"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(live.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    ok = live.probe_health("https://staging.example")
    assert ok["available"] is True
    assert ok["git_sha"] == "deadbeef"


def test_dashboard_never_guesses_production(monkeypatch):
    from app.releases import dashboard
    from app.releases.git_info import BranchInfo, GitSnapshot

    tip_sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    main_sha = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

    monkeypatch.setattr(
        dashboard,
        "collect_git_snapshot",
        lambda: GitSnapshot(
            available=True,
            branch="feature/releases-dashboard",
            commit=tip_sha,
            short_commit="aaaaaaa",
            main_sha=main_sha,
            branches=[
                BranchInfo(
                    name="feature/releases-dashboard",
                    tip_sha=tip_sha,
                    merged_into_main=False,
                )
            ],
        ),
    )
    monkeypatch.setattr(
        dashboard,
        "load_experiments",
        lambda: [
            {
                "id": "releases-dashboard",
                "name": "Releases dashboard",
                "objective": "Tracker",
                "branch": "feature/releases-dashboard",
                "decision": "testing",
                "decision_label": "Testing",
                "commit_id": tip_sha,
            }
        ],
    )
    monkeypatch.setattr(dashboard, "experiments_by_branch", lambda: {})
    monkeypatch.setattr(
        dashboard,
        "load_registry_document",
        lambda: {"experiments": [], "history": [], "source": "local", "path": "x"},
    )
    monkeypatch.setattr(
        dashboard,
        "load_staging_record",
        lambda: {"available": False, "source": "recorded", "status": "Unknown"},
    )
    monkeypatch.setattr(
        dashboard,
        "load_production_record",
        lambda: {
            "available": True,
            "git_sha": "cccccccccccccccccccccccccccccccccccccccc",
            "revision": "prod-rev",
            "image": "img@sha256:x",
            "branch": "main",
            "deployed_at": "2026-01-01T00:00:00Z",
        },
    )
    # Production health has no git_sha — must not treat record as live-verified.
    monkeypatch.setattr(
        dashboard,
        "probe_health",
        lambda url: {
            "available": True,
            "source": "live",
            "status": "Live",
            "git_sha": "Unknown",
            "ok": True,
        }
        if url and "prod" in url
        else {
            "available": False,
            "source": "live",
            "status": "Not Verified",
            "detail": "Base URL not configured",
        },
    )
    monkeypatch.setattr(dashboard, "find_reports_for_sha", lambda *a, **k: [])
    monkeypatch.setattr(dashboard, "latest_summary_unscoped", lambda: None)
    monkeypatch.setattr(dashboard, "STAGING_BASE_URL", "")
    monkeypatch.setattr(dashboard, "PRODUCTION_BASE_URL", "https://prod.example")
    monkeypatch.setattr(dashboard, "is_ancestor", lambda tip, env: False)

    dashboard.clear_cache()
    data = dashboard.get_dashboard(force=True)
    assert data["production"]["verified"] is False
    assert data["production"]["serving_sha"] is None
    assert "not live-verified" in data["production"]["verification_label"].lower()
    assert data["experiments"][0]["in_production"] == "unknown"
    assert data["base"]["source"] == "unknown"


def test_dashboard_verifies_when_health_matches_record(monkeypatch):
    from app.releases import dashboard
    from app.releases.git_info import GitSnapshot

    sha = "dddddddddddddddddddddddddddddddddddddddd"
    monkeypatch.setattr(
        dashboard,
        "collect_git_snapshot",
        lambda: GitSnapshot(available=True, main_sha=sha, branches=[]),
    )
    monkeypatch.setattr(dashboard, "load_experiments", lambda: [])
    monkeypatch.setattr(dashboard, "experiments_by_branch", lambda: {})
    monkeypatch.setattr(
        dashboard,
        "load_registry_document",
        lambda: {"experiments": [], "history": [], "source": "local", "path": "x"},
    )
    monkeypatch.setattr(
        dashboard,
        "load_staging_record",
        lambda: {
            "available": True,
            "git_sha": sha,
            "branch": "feature/x",
            "revision": "stg-1",
            "deployed_at": "2026-01-02T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        dashboard,
        "load_production_record",
        lambda: {"available": False, "status": "Unknown"},
    )
    monkeypatch.setattr(
        dashboard,
        "probe_health",
        lambda url: {
            "available": True,
            "git_sha": sha[:7],
            "status": "Live",
            "ok": True,
        }
        if url
        else {"available": False, "status": "Not Verified"},
    )
    monkeypatch.setattr(dashboard, "find_reports_for_sha", lambda *a, **k: [])
    monkeypatch.setattr(dashboard, "latest_summary_unscoped", lambda: None)
    monkeypatch.setattr(dashboard, "STAGING_BASE_URL", "https://staging.example")
    monkeypatch.setattr(dashboard, "PRODUCTION_BASE_URL", "")

    dashboard.clear_cache()
    data = dashboard.get_dashboard(force=True)
    assert data["staging"]["verified"] is True
    assert data["staging"]["serving_sha_short"] == sha[:7]
