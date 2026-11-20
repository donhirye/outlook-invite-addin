# Staging environment (WhatsApp PTSA bot)

A small, separate copy of the bot for experiments (prompts, models, routing, retrieval) that **cannot message parents** and **cannot touch production data**.

| | Production | Staging |
|---|---|---|
| GCP project | `vi1234` | `vi1234-staging` |
| Cloud Run service | `whatsapp-faq-bot` | `whatsapp-faq-bot-staging` |
| Bucket | `vi1234-whatsapp-faq` | `vi1234-staging-whatsapp-faq` |
| OpenAI key | production key | separate staging project + key |
| WhatsApp | connected (webhook, tokens) | **none** — webhook returns 404, sends blocked |
| Deploy | GitHub Actions from `main`, with approval | `scripts/deploy-staging.ps1` (committed HEAD) |
| Admin pages | same pages | same pages + red **STAGING** banner + **Test Chat** |

## How it stays safe

- `APP_ENV=staging` is the only thing that switches staging features on. If `APP_ENV` is unset (production) or anything other than exactly `staging`, the app behaves as production and Test Chat does not exist (404).
- Staging refuses to start unless `ADMIN_PASSWORD` (12+ chars) and `SECRET_KEY` (32+ chars) are non-default, and unless no `WHATSAPP_ACCESS_TOKEN` is set.
- Every WhatsApp send is blocked in code (`app/whatsapp.py`). `/webhook` is disabled. `/docs` is disabled. `/metrics` needs login.
- Credentials live in Secret Manager in the staging project only, never in Git.
- Deploys run as a staging-only service account (impersonation); it has no rights in `vi1234`.
- Only reference data (FAQ, calendar, guided flows) is copied from production, read-only. Parent conversations, analytics and traces are never copied.

## Test Chat

`https://<staging-url>/admin/test-chat` (log in at `/admin/login` first). It runs your message through the **same `process_message` pipeline** as WhatsApp, as a fake persona (parent A, parent B, FAQ admin), and shows route, flow, FAQ match, sources, tokens, estimated cost, latency, and trace id. Choice buttons work like WhatsApp reply buttons. "Reset" clears that persona's conversation.

JSON endpoint (same login cookie): `POST /admin/test-chat/api/message` with `{"persona":"parent_a","text":"..."}`; `POST /admin/test-chat/api/reset`; `GET /admin/test-chat/api/personas`.

Traces and analytics from Test Chat are tagged `channel=test_chat`.

## Daily use

```powershell
git checkout main; git pull; git checkout -b feature/my-experiment
# ...edit, commit...
.\whatsapp-hello-bot\scripts\deploy-staging.ps1
```

The script refuses uncommitted tracked changes (it deploys the commit), prints commit/revision/URL, and runs smoke tests (set `$env:STAGING_ADMIN_PASSWORD` to include a real login + chat turn).

### Evals from your laptop against staging

```powershell
$env:STAGING_ADMIN_PASSWORD = "<from your password manager>"
cd whatsapp-hello-bot
.venv\Scripts\python.exe -m evals.run --base-url https://<staging-url> --live-model --max-llm-calls 150
```

Results go to `evals/reports/staging_*.json` (gitignored); the committed deterministic baselines are untouched. The run stops at `--max-llm-calls` and refuses to run against a service with no Test Chat (e.g. production).

## Spending controls

- **OpenAI project limit (enforced):** set a $20/month **hard limit** on the staging OpenAI project. When reached, requests fail with 429 `project_spend_limit_exceeded`. Enforcement is not instantaneous, so keep headroom. Also set email alerts (e.g. $10, $16).
- **GCP budget (alerts only):** the $20 budget emails you at 50/80/100%; it does **not** stop anything.
- **Cloud Run:** `min-instances=0`, `max-instances=2` bounds compute.

## One-time setup (requires approval; not part of daily use)

```powershell
.\whatsapp-hello-bot\scripts\provision-staging.ps1 -DryRun   # review
.\whatsapp-hello-bot\scripts\provision-staging.ps1           # creates project, SAs, bucket, secrets, budget alert
.\whatsapp-hello-bot\scripts\provision-staging.ps1 -SetOpenAiKey   # after you create the staging OpenAI key
.\whatsapp-hello-bot\scripts\seed-staging-data.ps1
.\whatsapp-hello-bot\scripts\deploy-staging.ps1
```

The generated staging admin password is printed once during provisioning — save it in a password manager.

## Promoting an experiment

Staging result looks good → PR to `main` → review → merge → then explicitly ask for a **production** deploy via the GitHub Actions workflow. Staging never promotes itself.
