# Releases dashboard (local DEV)

Read-only Development & Release view at `/admin/releases` when `APP_ENV=development`.

It is **not** registered on staging or production Cloud Run.

## What you see

1. **DEV** — current branch/commit, dirty files, feature branches, PRs (`gh` when available), experiment registry
2. **STAGING / PROD** — **Recorded** deploy JSON vs **Live** `/health` probe
3. **Promotion matrix** — feature × DEV/STAGING/PROD from git ancestry (Unknown when SHAs missing)
4. **Git diagram** — simplified Mermaid of main + tips + deploy markers

## Setup

```powershell
cd whatsapp-hello-bot
copy .env.development.example .env.development
# set STAGING_BASE_URL / PRODUCTION_BASE_URL for live probes
.\scripts\run-dev.ps1
# open http://127.0.0.1:8080/admin/releases
```

Edit experiment names in [`whatsapp-hello-bot/data/experiments.json`](../whatsapp-hello-bot/data/experiments.json).

## Deployment records

| Source | File | Written by |
|--------|------|------------|
| Staging | `data/releases/staging-latest.json` | `scripts/deploy-staging.ps1` |
| Production | `data/releases/production-latest.json` | GitHub Actions artifact → `scripts/pull-production-release-record.ps1` |

JSON files are gitignored. Refresh the dashboard after pulling/writing records.

## Live vs recorded

- **Recorded** = last deploy script / artifact (what was intended to ship)
- **Live** = HTTP GET `{STAGING,PRODUCTION}_BASE_URL/health` (`status`, `app_env`, `git_sha`)
- Missing data shows **Unknown** / **Not Verified** — never invented

## Security

- Dashboard is login-protected and read-only (refresh only)
- No merge, deploy, or Cloud write from the app
- No secrets in `/health` or release JSON
