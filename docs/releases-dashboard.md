# Releases dashboard (staging experiment tracker)

Authenticated page at `/admin/releases` when `APP_ENV` is `staging` or `development`.

**Not** registered in production. Never merges, deploys, or changes Cloud Run from the UI.

## What you see

1. **Staging / Production cards** — verified serving commit when live `/health` provides `git_sha` (and matches the deploy record when both exist). Otherwise **Not verified** / **Unknown**.
2. **Experiments table** — Feature, Decision (Testing / Accepted / Parked / Rejected), In Staging?, In Main?, In Production?
3. **Waiting for Production** — Accepted + in Main, not verified in Production.
4. **Technical details** — SHAs, images, decision history (collapsed).

## Decisions storage

| Host | Location |
|------|----------|
| Staging | `gs://vi1234-staging-whatsapp-faq/releases/experiments/decisions.json` |
| Local DEV | `whatsapp-hello-bot/data/experiments.json` |

Saving a decision appends an audit history entry. It does **not** write to Git or Production.

## How status is verified

| Signal | Staging | Production (today) |
|--------|---------|----------------------|
| `/health` `git_sha` | Yes | **No** (health returns `{status:ok}` only) |
| Deploy record (revision, image, git_sha) | Yes (GCS `releases/staging-latest.json`) | Actions artifact / optional `releases/production-latest.json` |
| Live-verified serving commit | When health `git_sha` matches record (or health alone) | **Not available** until production `/health` exposes `git_sha` **or** you approve read-only Cloud Run access |

**Never guess.** If production cannot be live-verified, the Production card shows **Recorded — not live-verified** (when a record exists) and **In Production?** stays **Unknown**.

### Optional next step (needs your separate approval)

Grant the staging runtime service account **read-only** `roles/run.viewer` on the production service (or project) so the dashboard can read the serving revision/image/traffic split directly. Do **not** implement that without approval.

Better long-term fix (also separate): set `GIT_SHA` on production deploys so `/health` can confirm the serving commit without extra IAM.

## Workflow reminder

Create branch → deploy staging → test → decide → if Accepted, merge to main → deploy main to staging → validate → manual Production Actions release.
