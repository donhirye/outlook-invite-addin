# Local DEV (laptop)

Isolated `APP_ENV=development` for AI/RAG experiments. Staging remains the Cloud Run
release-validation environment. Production deploys only via GitHub Actions
`workflow_dispatch` on `main` (merge does **not** auto-deploy).

## Two folders (recommended)

| Folder | Role | Typical branch |
|--------|------|----------------|
| `C:\Users\mihir\Projects\outlook-invite-addin-local-dev` | **Experiments** (AI, Releases dashboard, scratch) | `experiment/*` or `feature/*` |
| `C:\Users\mihir\Projects\outlook-invite-addin` | **Release prep** (PRs, staging/prod deploy scripts) | `main` or a short-lived `feature/*` for promotion |

They share one Git object database (linked worktrees). Commit in the local-dev
worktree; cherry-pick or merge into a feature branch in the original folder only
when you are ready to promote. Never experiment directly on `main`.

## Start (from the local-dev worktree)

```powershell
cd C:\Users\mihir\Projects\outlook-invite-addin-local-dev\whatsapp-hello-bot
.\scripts\run-dev.ps1
```

First run copies `.env.development.example` → `.env.development` and exits until you
set a **DEV-only** `OPENAI_API_KEY`. Never reuse production or staging keys.

- URL: http://127.0.0.1:8000/admin (bound to localhost only)
- Releases: http://127.0.0.1:8000/admin/releases
- Stop: Ctrl+C in the terminal
- Data: `whatsapp-hello-bot/data/dev/` (gitignored; per worktree)
- Reseed: `.\scripts\run-dev.ps1 -Seed` or delete `data\dev` and re-run

## Safety

- Does not load `.env` (prod/staging secrets)
- Refuses startup if `FAQ_GCS_BUCKET` is set
- WhatsApp sends hard-blocked even when tokens are present
- Staging/production deploy scripts refuse experimental/local-dev branches

## Promote experiments

1. Prove the change in the **local-dev** worktree.
2. Commit there on `experiment/*` or `feature/*`.
3. In the **original** folder, create/update a promotion `feature/*` from latest `main`, bring the commits across, open a PR → `main`.
4. Do **not** merge or deploy without explicit approval.
5. Staging deploy (when asked): `.\scripts\deploy-staging.ps1` from a non-experimental branch in the original folder.
6. Production: only via the GitHub Actions workflow after merge to `main` and an explicit request.
