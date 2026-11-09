---
name: whatsapp-bot-dev-flow
description: >-
  Runs the WhatsApp PTSA bot release workflow for outlook-invite-addin /
  whatsapp-hello-bot. Use when the user wants to write new code, check in
  locally, push to GitHub, merge to main, or deploy to Cloud Run; also when
  they say phrases like "I want to write some new code", "ready to check this
  in", "move this to github", or "deploy". Applies on laptop Cursor and
  Cursor mobile / Cloud Agents with different mechanics but the same stages.
---

# WhatsApp bot dev & release flow

Repo: `donhirye/outlook-invite-addin`  
App: `whatsapp-hello-bot/`  
Production: Cloud Run `whatsapp-faq-bot` (`vi1234`, `us-central1`)  
Deploy workflow: `.github/workflows/deploy-cloud-run.yml` (manual `workflow_dispatch` only)

## Detect environment

| Signal | Mode |
|---|---|
| Workspace is the user’s laptop checkout under `Projects/outlook-invite-addin` | **Laptop** |
| Cloud Agent / Cursor mobile / no local `.git` write access like a laptop clone | **Mobile/Cloud** |

Same user phrases. Different behind-the-scenes steps.

## User phrase → stage

| User says (same idea) | Stage | What happens |
|---|---|---|
| “I want to write some new code” / start a feature | **1. Start** | Sync `main`, create feature branch, implement + test. Do **not** commit/push/deploy unless asked. |
| “Ready to check this in” / save local history | **2. Check in** | **Laptop:** local `git commit` only. **Mobile/Cloud:** commit on the agent branch (usually already remote-capable). Do **not** merge or deploy. |
| “Move this to GitHub” / push upstream | **3. GitHub** | Push feature branch; open/update PR → `main`. Do **not** merge or deploy unless asked. |
| “Deploy” / ship to users | **4. Deploy** | Ensure changes are on GitHub `main` (merge PR with explicit approval if needed), then run Actions deploy to Cloud Run. |

Correct mental model:

```text
feature branch → local commit → push/PR on GitHub → merge to main → Actions deploy → Cloud Run
```

Never deploy uncommitted laptop files. Never deploy a feature branch directly. Never deploy on merge automatically.

## Safety (always)

Ask before:

- Merging into `main`
- Triggering Cloud Run deploy / Actions `dry_run=false`
- Rotating credentials
- Deleting data / destructive git (`reset --hard`, force-push)

Never:

- Commit `.env`, `.venv`, private CSVs, or `learning/` private data
- Use `--set-env-vars` on deploy (preserves existing Cloud Run config)
- Force-push `main`

Prefer feature branch names like `feature/short-description`.

---

## Stage 1 — Start (“I want to write some new code”)

### Laptop

1. `git fetch origin` && `git checkout main` && `git pull origin main`
2. `git checkout -b feature/<short-name>`
3. Implement in `whatsapp-hello-bot/` (or agreed paths)
4. Run relevant tests (`pytest` in `whatsapp-hello-bot`)
5. Summarize what changed; stop until check-in

### Mobile / Cloud Agent

1. Base work on latest `main` of `donhirye/outlook-invite-addin`
2. Create/use a feature branch (not direct commits to `main`)
3. Implement + test in the cloud environment
4. Summarize; wait for check-in / PR instructions

Do not touch production FAQ GCS content unless the task is explicitly about FAQ content via admin APIs.

---

## Stage 2 — Check in (“ready to check this in”)

Means **record history**, not production.

### Laptop

1. `git status` / `git diff`
2. Stage only intended files
3. Create a local commit (concise message)
4. Confirm branch is still **ahead of origin** or has local commits not pushed
5. Tell the user: saved locally; say when to move to GitHub

### Mobile / Cloud Agent

1. Commit on the feature branch
2. If the agent environment requires push to persist, push the **feature branch only** and say so
3. Do not merge to `main`

---

## Stage 3 — GitHub (“move this to GitHub”)

### Laptop

1. `git push -u origin HEAD` (feature branch)
2. Open or update a PR targeting `main`
3. Paste PR URL; do **not** merge unless user asks

### Mobile / Cloud Agent

1. Ensure feature branch is pushed
2. Open/update PR → `main` (ask agent to “open the PR” if the mobile UI needs it)
3. Do **not** merge unless user asks

“Move all this to GitHub” means **the current feature branch + PR**, not every local branch on the machine, and not merging to `main` by default.

---

## Stage 4 — Deploy (“deploy”)

Production users only see changes after **`main` + Cloud Run revision**.

1. Confirm intended commits are in the PR / on the feature branch  
2. **Merge PR → `main`** only after user approval (if not already merged)  
3. Run GitHub Actions workflow **Deploy WhatsApp bot to Cloud Run** on `main`  
   - First verification in a session may use `dry_run=true`  
   - Production ship: `dry_run=false` with user approval  
4. Approve GitHub `production` environment if required  
5. Verify `/health`, note revision + SHA; report rollback revision  

Rollback:

```powershell
gcloud run services update-traffic whatsapp-faq-bot --region us-central1 --project vi1234 --to-revisions=PREVIOUS_REVISION=100
```

Docs: `docs/deployment-guide.md`, `docs/github-actions-wif-setup.md`

---

## Learning workspace

`learning/` is separate practice. Do not deploy it. Do not mix learning commits into production deploys unless the user explicitly asks for a docs-only change.

## Response style

After each stage, reply briefly with:

- Mode: Laptop or Mobile/Cloud  
- Branch name  
- What was done  
- What the user should say next (check in / GitHub / deploy)
