# Operating guide — branch, staging experiment, restore, merge, prod

Approved simplified flow (image-digest promotion is **deferred**; prod stays manual Actions).

## Daily loop

1. `git checkout main && git pull`
2. `git checkout -b feature/<short-name>` (or `experiment/<short-name>`)
3. Commit tracked changes
4. Deploy to staging: `.\whatsapp-hello-bot\scripts\deploy-staging.ps1`
5. Validate Test Chat + Releases + FAQ on staging
6. If good → open PR → merge to `main`
7. Optionally redeploy staging from `main` (baseline FAQ) to confirm
8. Production: run the GitHub Actions **workflow_dispatch** deploy (approval). Do **not** auto-promote by image digest yet.

## Staging experiment deploy

- Allowed branches: `main`, `feature/*`, `experiment/*`
- Blocked: laptop-only names (`experiment/local-scratch`, `*/local-dev*`, `wip/*`, …)
- Hard refuse: production project/service (`vi1234` / `whatsapp-faq-bot`)
- Deploys **git archive HEAD** (commit), not the dirty working tree

### FAQ + embedding isolation

For `feature/*` and `experiment/*`, deploy sets `FAQ_GCS_PREFIX=experiments/<branch-slug>/` and copies baseline FAQ / index / faq_records into that prefix **only if missing**. Baseline object names are never overwritten.

- Service reads: `gs://vi1234-staging-whatsapp-faq/experiments/<slug>/science_olympiad_faq.txt` (+ `.index.json`)
- Baseline remains: `gs://…/science_olympiad_faq.txt`

Force baseline objects (e.g. after restore): `.\deploy-staging.ps1 -BaselineFaq`

## Restore known-good staging

A crashing experiment can take down staging admin (including Releases) until restore:

```powershell
.\whatsapp-hello-bot\scripts\restore-staging.ps1
# or force main:
.\whatsapp-hello-bot\scripts\restore-staging.ps1 -FromMain
```

Uses `gs://…/releases/staging-known-good.json` when present (last smoke-passing deploy), else `origin/main`. Clears `FAQ_GCS_PREFIX` so FAQ returns to baseline.

## Production

- Keep **manual** `workflow_dispatch` in `.github/workflows/deploy-cloud-run.yml`
- Continue recording commit SHA + container image in `production-latest.json`
- Image-digest promote from staging → prod is **out of scope** for now
- Pull the artifact locally: `.\whatsapp-hello-bot\scripts\pull-production-release-record.ps1`

## Releases dashboard

Staging: `https://<staging-url>/admin/releases` (after login).  
See [releases-dashboard.md](releases-dashboard.md).

## Local-dev worktree

Keep the separate local-dev worktree until staging Releases is validated and valuables are retained. Do **not** delete the worktree or DEV-only paths without an explicit later approval (Phase 6).

## Rollback mental model

| Layer | Action |
|-------|--------|
| Staging broken by experiment | `restore-staging.ps1` |
| Prod bad revision | Re-run Actions deploy for a prior known commit (manual) |
| FAQ experiment data | Leave prefixed objects; redeploy with `-BaselineFaq` or restore |
