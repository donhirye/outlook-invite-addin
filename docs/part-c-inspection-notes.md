# Part C inspection notes (read-only findings)

Captured before adding the GitHub Actions workflow.

## GitHub Actions

- No existing workflows under `.github/workflows/`
- Repo has a `github-pages` environment only
- No `production` environment yet
- Branch protection / environment APIs require authenticated admin access to verify from automation

## Application packaging

- `whatsapp-hello-bot/Dockerfile` copies only `requirements.txt`, `app/`, `data/`, `privacy-policy.html`
- `.gcloudignore` excludes `.env`, `.venv`, playground, learnings, CSVs, tests, docs
- `.dockerignore` mirrors those exclusions for the image build context

## Cloud Run (project `vi1234`, region `us-central1`)

- Service: `whatsapp-faq-bot`
- Latest ready revision at inspection time: `whatsapp-faq-bot-00009-pjx`
- Runtime service account: default Compute Engine SA
- FAQ durability: env `FAQ_GCS_BUCKET=vi1234-whatsapp-faq` (+ object/index env vars)
- App configuration secrets currently stored as **plain service env vars** (not Secret Manager)
- Manual deploy historically used `gcloud run deploy --source .`

## IAM / WIF

- Existing custom SA: `vi1234-svc1@vi1234.iam.gserviceaccount.com`
- Runtime Compute SA currently has broad `roles/editor` on the project
- **No** Workload Identity pools exist yet
- Creating WIF + a dedicated deploy SA requires your explicit approval (see `github-actions-wif-setup.md`)

## Settings the workflow must preserve

- Existing Cloud Run environment variable names/values
- Runtime service account
- Ingress / auth settings (workflow does not change them)
- GCS FAQ object contents
- Prior revisions (no deletion)
