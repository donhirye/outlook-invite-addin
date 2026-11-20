"""Releases dashboard — DEV-only routes + pure helpers (no Cloud writes)."""

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


def test_releases_available_only_in_development():
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
  "has_funnel": "Promotion funnel" in page.text and "BASE" in page.text,
  "has_staging_pill": "STAGING" in page.text,
  "no_top_dev_card": "Local workspace" not in page.text,
  "no_deploy_detail": "Smoke:" not in page.text and "Container image" not in page.text,
  "no_deploy_button": "Deploy to" not in page.text,
  "has_refresh": "/admin/releases/refresh" in page.text,
}))
""",
        APP_ENV="development",
    )
    assert dev["anon"] in {302, 303}
    assert dev["page"] == 200
    assert dev["has_funnel"] is True
    assert dev["has_staging_pill"] is True
    assert dev["no_top_dev_card"] is True
    assert dev["no_deploy_detail"] is True
    assert dev["no_deploy_button"] is True
    assert dev["has_refresh"] is True

    staging = _run(
        """
import json
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app, follow_redirects=False)
r = c.get("/admin/releases")
print(json.dumps({"status": r.status_code}))
""",
        APP_ENV="staging",
        ADMIN_PASSWORD="unit-test-staging-password",
        SECRET_KEY="unit-test-staging-secret-key-0123456789",
        DOTENV_PATH="",
    )
    assert staging["status"] == 404

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


def test_registry_and_records(tmp_path, monkeypatch):
    from app.releases import records, registry

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
                        "status": "experimental",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(registry, "REGISTRY_PATH", reg)
    items = registry.load_experiments()
    assert items[0]["name"] == "Demo"
    assert registry.experiments_by_branch()["feature/demo"]["objective"] == "Try things"

    releases = tmp_path / "releases"
    releases.mkdir()
    staging = releases / "staging-latest.json"
    staging.write_text(
        json.dumps(
            {
                "git_sha": "1111111111111111111111111111111111111111",
                "revision": "rev-1",
                "image": "img@sha256:abc",
                "deployed_at": "2026-01-01T00:00:00Z",
                "smoke_ok": True,
                "service": "whatsapp-faq-bot-staging",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(records, "RELEASES_DIR", releases)
    monkeypatch.setattr(records, "STAGING_RECORD", staging)
    monkeypatch.setattr(records, "PRODUCTION_RECORD", releases / "production-latest.json")
    st = records.load_staging_record()
    assert st["available"] is True
    assert st["source"] == "recorded"
    assert st["revision"] == "rev-1"
    prod = records.load_production_record()
    assert prod["available"] is False
    assert prod["status"] == "Unknown"


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
    assert ok["app_env"] == "staging"


def test_matrix_and_dashboard_build_without_hardcoded_shas(monkeypatch):
    from app.releases import dashboard
    from app.releases.git_info import BranchInfo, GitSnapshot

    main_sha = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    tip_sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    monkeypatch.setattr(
        dashboard,
        "collect_git_snapshot",
        lambda: GitSnapshot(
            available=True,
            branch="feature/releases-dashboard",
            commit=tip_sha,
            short_commit="aaaaaaa",
            commit_subject="wip",
            commit_date="2026-01-01",
            dirty_files=[],
            main_sha=main_sha,
            branches=[
                BranchInfo(
                    name="feature/releases-dashboard",
                    tip_sha=tip_sha,
                    tip_date="2026-01-01",
                    tip_subject="wip",
                    ahead=2,
                    behind=0,
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
                "objective": "Visual lifecycle",
                "branch": "feature/releases-dashboard",
                "status": "experimental",
            }
        ],
    )
    monkeypatch.setattr(dashboard, "experiments_by_branch", lambda: {
        "feature/releases-dashboard": {
            "name": "Releases dashboard",
            "objective": "Visual lifecycle",
            "branch": "feature/releases-dashboard",
            "status": "experimental",
        }
    })
    monkeypatch.setattr(
        dashboard,
        "load_staging_record",
        lambda: {"available": False, "source": "recorded", "status": "Unknown"},
    )
    monkeypatch.setattr(
        dashboard,
        "load_production_record",
        lambda: {"available": False, "source": "recorded", "status": "Unknown"},
    )
    monkeypatch.setattr(
        dashboard,
        "probe_health",
        lambda url: {
            "available": False,
            "source": "live",
            "status": "Not Verified",
            "detail": "Base URL not configured",
        },
    )
    monkeypatch.setattr(dashboard, "find_reports_for_sha", lambda *a, **k: [])
    monkeypatch.setattr(dashboard, "latest_summary_unscoped", lambda: None)
    monkeypatch.setattr(dashboard, "STAGING_BASE_URL", "")
    monkeypatch.setattr(dashboard, "PRODUCTION_BASE_URL", "")
    monkeypatch.setattr(dashboard, "is_ancestor", lambda tip, env: tip == env)

    dashboard.clear_cache()
    data = dashboard.get_dashboard(force=True)
    assert data["base"]["source"] == "main_proxy"
    assert data["base"]["sha"] == main_sha
    assert data["formula"]["funnel"]["on_dev"] == 1
    assert data["formula"]["funnel"]["in_base"] == 0
    assert data["matrix"][0]["on_dev"] == "yes"
    assert data["matrix"][0]["on_prod"] == "no"
    assert data["matrix"][0]["on_staging"] == "unknown"  # no staging SHA
    assert "Releases dashboard" in data["formula"]["dev_expression"]
    assert data["formula"]["staging_expression"] == "Not Verified"
    assert "BASE" in data["mermaid"]


def test_funnel_counts_staging_extras_beyond_base(monkeypatch):
    from app.releases import dashboard
    from app.releases.git_info import BranchInfo, GitSnapshot

    base = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    stg = "cccccccccccccccccccccccccccccccccccccccc"
    feat_a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    monkeypatch.setattr(
        dashboard,
        "collect_git_snapshot",
        lambda: GitSnapshot(
            available=True,
            branch="feature/a",
            commit=feat_a,
            short_commit="aaaaaaa",
            commit_subject="a",
            commit_date="2026-01-01",
            dirty_files=[],
            main_sha=base,
            branches=[
                BranchInfo(name="feature/a", tip_sha=feat_a, merged_into_main=False),
            ],
        ),
    )
    monkeypatch.setattr(
        dashboard,
        "load_experiments",
        lambda: [
            {
                "id": "a",
                "name": "Feature A",
                "objective": "A",
                "branch": "feature/a",
                "status": "ready",
            }
        ],
    )
    monkeypatch.setattr(dashboard, "experiments_by_branch", lambda: {})
    monkeypatch.setattr(
        dashboard,
        "load_staging_record",
        lambda: {
            "available": True,
            "git_sha": stg,
            "source": "recorded",
            "status": "Recorded",
        },
    )
    monkeypatch.setattr(
        dashboard,
        "load_production_record",
        lambda: {
            "available": True,
            "git_sha": base,
            "source": "recorded",
            "status": "Recorded",
        },
    )
    monkeypatch.setattr(
        dashboard,
        "probe_health",
        lambda url: {"available": False, "source": "live", "status": "Not Verified"},
    )
    monkeypatch.setattr(dashboard, "find_reports_for_sha", lambda *a, **k: [])
    monkeypatch.setattr(dashboard, "latest_summary_unscoped", lambda: None)
    monkeypatch.setattr(dashboard, "STAGING_BASE_URL", "")
    monkeypatch.setattr(dashboard, "PRODUCTION_BASE_URL", "")

    def fake_ancestor(tip, env):
        if tip == feat_a and env == stg:
            return True
        if tip == feat_a and env == base:
            return False
        return False

    monkeypatch.setattr(dashboard, "is_ancestor", fake_ancestor)
    monkeypatch.setattr(dashboard, "commits_between", lambda a, b, **k: ["ccccccc Feature A"])

    dashboard.clear_cache()
    data = dashboard.get_dashboard(force=True)
    assert data["base"]["source"] == "production"
    assert data["matrix"][0]["on_staging"] == "yes"
    assert data["matrix"][0]["on_prod"] == "no"
    assert data["matrix"][0]["lane"] == "staging_candidate"
    assert data["formula"]["funnel"]["on_staging"] == 1
    assert data["formula"]["funnel"]["in_base"] == 0
    assert "Feature A" in data["formula"]["staging_expression"]
    assert data["formula"]["staging_expression"].startswith("BASE +")


def test_eval_report_match_by_git_sha(tmp_path, monkeypatch):
    from app.releases import evals as eval_mod

    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "staging_demo.json").write_text(
        json.dumps({"git_sha": "ffffeeee", "passed": 3, "failed": 1, "cases_run": 4}),
        encoding="utf-8",
    )
    monkeypatch.setattr(eval_mod, "REPORTS_DIR", reports)
    hits = eval_mod.find_reports_for_sha("ffffeeee0000")
    assert hits and hits[0]["passed"] == 3
    assert eval_mod.find_reports_for_sha(None) == []
