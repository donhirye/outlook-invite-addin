# How to deploy the WhatsApp bot (one-click)

This guide is for deploying **approved `main` code** to Google Cloud Run using GitHub Actions.

Laptop deploys still work, but the preferred path is: merge PR → open Actions → Run workflow.

## Before the first Actions deploy

Complete [github-actions-wif-setup.md](./github-actions-wif-setup.md) (needs your approval for Google Cloud IAM).

You need:

- GitHub environment named `production` (with you as required reviewer)
- Secrets `GCP_WORKLOAD_IDENTITY_PROVIDER` and `GCP_SERVICE_ACCOUNT`

## Deploy from a laptop browser

1. Merge your feature PR into `main` on GitHub.
2. Open the repo: https://github.com/donhirye/outlook-invite-addin
3. Click **Actions**
4. In the left list, click **Deploy WhatsApp bot to Cloud Run**
5. Click **Run workflow**
6. Leave **Use workflow from** set to **main**
7. First time / safety check: set **dry_run** to **true**
8. Click the green **Run workflow**
9. Open the new run. If `production` environment protection is on, click **Review deployments** → **Approve**
10. Wait for the green check. Open the run’s **Summary** for Git SHA + revision

When dry_run looks good, repeat steps 5–9 with **dry_run = false** to deploy for real.

## Deploy from your phone

1. Open the same GitHub repo in your phone browser (or GitHub mobile app → repository in browser).
2. Menu → **Actions** → **Deploy WhatsApp bot to Cloud Run**
3. **Run workflow** → branch **main** → choose dry_run → run
4. Approve the `production` environment if prompted
5. Watch the run until it finishes

Tip: add the Actions URL to your phone home screen:

`https://github.com/donhirye/outlook-invite-addin/actions/workflows/deploy-cloud-run.yml`

## How to see deployment status

- **Actions tab** → latest run of **Deploy WhatsApp bot to Cloud Run**
- Green check = success; red X = failure
- Click the run → **Summary** for SHA, previous revision, new revision, image digest
- Live service: https://whatsapp-faq-bot-7baznmhe7q-uc.a.run.app/health  
  Should return `{"status":"ok"}`

## How to find the currently deployed Git SHA

1. Open the latest **successful** Actions deploy run Summary (shows Git SHA)
2. Or compare Cloud Run revision time with the `main` commit history on GitHub
3. Optional local check after a deploy:

```powershell
gcloud run revisions describe REVISION_NAME --region us-central1 --project vi1234 --format="yaml(metadata.creationTimestamp,spec.containers[0].image)"
```

The workflow Summary always prints the exact `github.sha` that was deployed.

## Rollback a bad deploy

Cloud Run keeps old revisions. Deploy does **not** delete them.

If a new revision is unhealthy:

```powershell
# Example: send 100% traffic back to the previous revision
gcloud run services update-traffic whatsapp-faq-bot `
  --region us-central1 `
  --project vi1234 `
  --to-revisions=PREVIOUS_REVISION=100
```

Replace `PREVIOUS_REVISION` with the value from the Actions Summary (“Previous revision”).

Then open `/health` and send a WhatsApp test message from your allowlisted number.

## What this workflow will NOT do

- Deploy on every merge/push (manual **Run workflow** only)
- Deploy from a feature branch (`deploy` job requires `main`)
- Upload laptop-only files (uses the GitHub commit + `.gcloudignore`)
- Deploy when tests fail
- Overwrite the FAQ text in GCS
- Delete old revisions
- Rotate API tokens

## Troubleshooting

| Problem | What to try |
|---|---|
| Workflow missing in Actions | Confirm `.github/workflows/deploy-cloud-run.yml` is on `main` |
| “Missing GitHub secrets …” | Finish WIF setup; add `GCP_WORKLOAD_IDENTITY_PROVIDER` and `GCP_SERVICE_ACCOUNT` |
| Waiting forever on deploy job | Approve the `production` environment review request |
| Auth / permission errors from Google | Re-check WIF provider condition (`donhirye/outlook-invite-addin`) and deploy SA roles |
| Tests failed | Fix on a feature branch, merge to `main`, re-run workflow |
| Health check failed after deploy | Use rollback command above; inspect Cloud Run logs |
| FAQ answers wrong/missing | FAQ lives in GCS; deploy does not rewrite it — check `/admin/faq` |

## Laptop emergency deploy (backup)

Only if Actions is unavailable:

```powershell
cd C:\Users\mihir\Projects\outlook-invite-addin
git checkout main
git pull origin main
cd whatsapp-hello-bot
gcloud run deploy whatsapp-faq-bot --source . --region us-central1 --project vi1234
```
