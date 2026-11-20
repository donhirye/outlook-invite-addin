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

| Signal | Staging | Production |
|--------|---------|------------|
| Cloud Run describe (read-only) | Yes — revision, image, traffic | Yes — same (staging-runtime has `roles/run.viewer`) |
| `/health` `git_sha` | Yes | Not currently set on prod |
| Deploy record | GCS `releases/staging-latest.json` | GCS `releases/production-latest.json` |

Serving revision/image come from live Cloud Run. Commit is taken from the revision’s `GIT_SHA` when present, otherwise from a release record whose revision/image matches the live revision.

Table cells show **Yes** / **No** / **—** (not the word “Unknown”).

## Workflow reminder

Create branch → deploy staging → test → decide → if Accepted, merge to main → deploy main to staging → validate → manual Production Actions release.
