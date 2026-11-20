# Releases dashboard (staging + local DEV)

Authenticated read-only view at `/admin/releases` when `APP_ENV` is `staging` or `development`.

**Not** registered in production.

## Sections

| Section | Content |
|---------|---------|
| Funnel | PROD / STAGING / branch-tip formula + counts |
| A — Branch hierarchy | feature/experiment/cursor/hotfix tips vs main |
| B/C — Deploy versions | Recorded + live `/health` for staging and prod (commit, revision, image) |
| D — Matrix | Feature × tip / staging / prod ancestry |
| E — Evals | SHA-scoped staging eval reports when present |

## Data sources

| Environment | Branch metadata | Deploy records |
|-------------|-----------------|----------------|
| Local DEV | Laptop `git` + `gh` | `data/releases/*.json` |
| Staging Cloud Run | GitHub API (read-only PAT) | Local file if present, else `gs://…/releases/*.json` |

### Staging GitHub token (optional but recommended)

Create a fine-grained PAT with **Contents: Read** and **Metadata: Read** (Pull requests: Read if you want PR links). Store it in the staging project:

```powershell
# One-time (from a machine with staging deployer rights)
gcloud secrets create staging-github-token --project=vi1234-staging
# then add a version with the PAT value
```

`deploy-staging.ps1` mounts it as `GITHUB_TOKEN` when the secret exists. Without it, branch hierarchy shows Unknown / empty gracefully.

## Deployment records

| Source | Path | Writer |
|--------|------|--------|
| Staging (laptop) | `whatsapp-hello-bot/data/releases/staging-latest.json` | `deploy-staging.ps1` |
| Staging (GCS) | `gs://vi1234-staging-whatsapp-faq/releases/staging-latest.json` | same |
| Staging known-good | `gs://…/releases/staging-known-good.json` | deploy after smoke pass |
| Production | Actions artifact → `pull-production-release-record.ps1` | manual prod workflow |

## Security

- Login required; UI is read-only (refresh only)
- No merge/deploy/Cloud write from the app
- GitHub token is read-only; never used for pushes
