# Local DEV (laptop)

Isolated `APP_ENV=development` for AI/RAG experiments. Staging remains the Cloud Run
release-validation environment. Production deploys only via GitHub Actions
`workflow_dispatch` on `main` (merge does **not** auto-deploy).

## Start

```powershell
cd whatsapp-hello-bot
.\scripts\run-dev.ps1
```

First run copies `.env.development.example` → `.env.development` and exits until you
set a **DEV-only** `OPENAI_API_KEY`. Never reuse production or staging keys.

- URL: http://127.0.0.1:8000/admin (bound to localhost only)
- Stop: Ctrl+C in the terminal
- Data: `whatsapp-hello-bot/data/dev/` (gitignored)
- Reseed: `.\scripts\run-dev.ps1 -Seed` or delete `data\dev` and re-run

## Safety

- Does not load `.env` (prod/staging secrets)
- Refuses startup if `FAQ_GCS_BUCKET` is set
- WhatsApp sends hard-blocked even when tokens are present
- Staging/production deploy scripts refuse experimental/local-dev branches

## Promote experiments

1. Prove the change in local DEV.
2. Commit on an approved feature branch (not a scratch worktree tip you intend to abandon).
3. Open a PR → `main`. Do **not** merge or deploy without explicit approval.
4. Staging deploy (when asked): `.\scripts\deploy-staging.ps1` from a non-experimental branch.
5. Production: only via the GitHub Actions workflow after merge to `main` and an explicit request.
