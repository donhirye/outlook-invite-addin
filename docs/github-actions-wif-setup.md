# One-time setup: GitHub Actions → Google Cloud (Workload Identity Federation)

Do these steps **once**, with your approval, before the first GitHub Actions production deploy.

This guide creates a **dedicated deploy service account** and short-lived auth. It does **not** store a long-lived JSON key in GitHub.

## What already exists (inspected)

| Item | Current state |
|---|---|
| GitHub Actions workflows | None before this feature |
| Cloud Run service | `whatsapp-faq-bot` in `us-central1`, project `vi1234` |
| Runtime identity | Default Compute SA `…-compute@developer.gserviceaccount.com` |
| FAQ storage | GCS bucket `vi1234-whatsapp-faq` (env `FAQ_GCS_BUCKET`) |
| App secrets | Plain Cloud Run env vars today (not Secret Manager) |
| WIF pools | **None yet** |
| GitHub `production` environment | **Not created yet** (only `github-pages` exists) |

Deploy must **preserve** existing Cloud Run env vars, runtime SA, and GCS FAQ objects. The workflow intentionally does not pass `--set-env-vars`.

## A. Enable required APIs

In Cloud Shell or local `gcloud` (project `vi1234`):

```powershell
gcloud config set project vi1234

gcloud services enable `
  run.googleapis.com `
  cloudbuild.googleapis.com `
  artifactregistry.googleapis.com `
  iam.googleapis.com `
  iamcredentials.googleapis.com `
  cloudresourcemanager.googleapis.com `
  sts.googleapis.com `
  storage.googleapis.com
```

## B. Create a dedicated deploy service account

```powershell
gcloud iam service-accounts create github-actions-deploy `
  --display-name="GitHub Actions Cloud Run deploy"
```

Email will be:

`github-actions-deploy@vi1234.iam.gserviceaccount.com`

### Minimum roles (project)

```powershell
$DEPLOY_SA = "github-actions-deploy@vi1234.iam.gserviceaccount.com"
$RUNTIME_SA = "549654673961-compute@developer.gserviceaccount.com"
$PROJECT_NUMBER = gcloud projects describe vi1234 --format="value(projectNumber)"

# Deploy / build / push images
gcloud projects add-iam-policy-binding vi1234 --member="serviceAccount:$DEPLOY_SA" --role="roles/run.admin"
gcloud projects add-iam-policy-binding vi1234 --member="serviceAccount:$DEPLOY_SA" --role="roles/cloudbuild.builds.editor"
gcloud projects add-iam-policy-binding vi1234 --member="serviceAccount:$DEPLOY_SA" --role="roles/artifactregistry.writer"
gcloud projects add-iam-policy-binding vi1234 --member="serviceAccount:$DEPLOY_SA" --role="roles/storage.admin"
gcloud projects add-iam-policy-binding vi1234 --member="serviceAccount:$DEPLOY_SA" --role="roles/viewer"

# Allow deploy SA to deploy as the existing runtime SA (do not change the runtime SA)
gcloud iam service-accounts add-iam-policy-binding $RUNTIME_SA `
  --member="serviceAccount:$DEPLOY_SA" `
  --role="roles/iam.serviceAccountUser"
```

> `roles/storage.admin` is broader than ideal; it is commonly needed for Cloud Build source buckets used by `gcloud run deploy --source`. After the first successful deploy, we can tighten this to specific buckets if you want.

## C. Create Workload Identity Pool + GitHub provider

```powershell
$PROJECT_NUMBER = gcloud projects describe vi1234 --format="value(projectNumber)"

gcloud iam workload-identity-pools create "github-pool" `
  --location="global" `
  --display-name="GitHub Actions pool"

gcloud iam workload-identity-pools providers create-oidc "github-provider" `
  --location="global" `
  --workload-identity-pool="github-pool" `
  --display-name="GitHub provider" `
  --issuer-uri="https://token.actions.githubusercontent.com" `
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref,attribute.actor=assertion.actor" `
  --attribute-condition="assertion.repository=='donhirye/outlook-invite-addin'"
```

Bind the pool to the deploy SA (**main branch workflow only**):

```powershell
$DEPLOY_SA = "github-actions-deploy@vi1234.iam.gserviceaccount.com"
$PROJECT_NUMBER = gcloud projects describe vi1234 --format="value(projectNumber)"
$PRINCIPAL = "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/attribute.repository/donhirye/outlook-invite-addin"

gcloud iam service-accounts add-iam-policy-binding $DEPLOY_SA `
  --role="roles/iam.workloadIdentityUser" `
  --member="$PRINCIPAL"
```

Provider resource name (save this):

```powershell
gcloud iam workload-identity-pools providers describe github-provider `
  --location=global `
  --workload-identity-pool=github-pool `
  --format="value(name)"
```

Looks like:

`projects/549654673961/locations/global/workloadIdentityPools/github-pool/providers/github-provider`

## D. GitHub repository settings (browser)

1. Open **Settings → Environments → New environment**
2. Name: `production`
3. Enable **Required reviewers** (add yourself)
4. Deployment branches: **Selected branches** → allow only `main`
5. Open **Settings → Secrets and variables → Actions**
6. Add repository secrets:
   - `GCP_WORKLOAD_IDENTITY_PROVIDER` = provider resource name from step C
   - `GCP_SERVICE_ACCOUNT` = `github-actions-deploy@vi1234.iam.gserviceaccount.com`
7. Optional variable:
   - `CLOUD_RUN_SERVICE_URL` = `https://whatsapp-faq-bot-7baznmhe7q-uc.a.run.app`

8. Open **Settings → Branches → Add rule** for `main` (recommended):
   - Require a pull request before merging
   - Do not allow force pushes

## E. First safe validation

After the workflow is merged to `main`:

1. Actions → **Deploy WhatsApp bot to Cloud Run** → Run workflow
2. Branch: `main`
3. Set **dry_run = true**
4. Confirm tests + WIF auth succeed with **no** new Cloud Run revision

Only then run again with **dry_run = false** (still requires the `production` environment approval).

## What this does NOT do

- Does not rotate WhatsApp/OpenAI credentials
- Does not move env vars into Secret Manager (optional later)
- Does not delete old Cloud Run revisions
- Does not overwrite GCS FAQ content
- Does not deploy from feature branches
