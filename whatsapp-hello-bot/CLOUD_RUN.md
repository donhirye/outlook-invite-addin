# Deploy WhatsApp FAQ bot to Google Cloud Run

This replaces ngrok with a stable HTTPS URL.

## Prerequisites

1. Google Cloud project with billing enabled
2. `gcloud` CLI installed and logged in
3. Your secrets ready (WhatsApp + OpenAI)

## One-time setup

```bash
# set these
export PROJECT_ID=your-gcp-project-id
export REGION=us-central1
export SERVICE_NAME=whatsapp-faq-bot
export FAQ_BUCKET=${PROJECT_ID}-whatsapp-faq

gcloud config set project $PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com

# Durable FAQ + embedding index (shared by admin UI and WhatsApp /faq)
gcloud storage buckets create gs://$FAQ_BUCKET --location=$REGION --uniform-bucket-level-access
```

PowerShell:

```powershell
$env:PROJECT_ID = "vi1234"
$env:REGION = "us-central1"
$env:SERVICE_NAME = "whatsapp-faq-bot"
$env:FAQ_BUCKET = "$($env:PROJECT_ID)-whatsapp-faq"

gcloud config set project $env:PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com
gcloud storage buckets create "gs://$($env:FAQ_BUCKET)" --location=$env:REGION --uniform-bucket-level-access
```

## Deploy

From `whatsapp-hello-bot/`:

```bash
gcloud run deploy $SERVICE_NAME \
  --source . \
  --region $REGION \
  --allow-unauthenticated \
  --set-env-vars "WHATSAPP_VERIFY_TOKEN=my-verify-token,WHATSAPP_PHONE_NUMBER_ID=YOUR_PHONE_ID,OPENAI_MODEL=gpt-5.6-luna,FAQ_ADMIN_PHONES=18122165774,ADMIN_PASSWORD=changeme,SECRET_KEY=long-random-string,FAQ_GCS_BUCKET=${FAQ_BUCKET},FAQ_GCS_OBJECT=science_olympiad_faq.txt,FAQ_TOP_K=4"
```

PowerShell one-liner redeploy:

```powershell
gcloud run deploy whatsapp-faq-bot --source . --region us-central1 --allow-unauthenticated --update-env-vars "FAQ_GCS_BUCKET=vi1234-whatsapp-faq,FAQ_GCS_OBJECT=science_olympiad_faq.txt,FAQ_GCS_INDEX_OBJECT=science_olympiad_faq.txt.index.json,FAQ_TOP_K=4"
```

Then set sensitive env vars in Cloud Run console (or Secret Manager):

- `WHATSAPP_ACCESS_TOKEN`
- `OPENAI_API_KEY`

### Grant the Cloud Run service account access to the bucket

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud storage buckets add-iam-policy-binding gs://$FAQ_BUCKET \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/storage.objectAdmin"
```

## Admin UI

After deploy:

- Greeting: `https://YOUR-SERVICE-URL/admin`
- FAQ editor: `https://YOUR-SERVICE-URL/admin/faq`

Password is `ADMIN_PASSWORD`. The FAQ page always loads the latest durable FAQ, including entries added via WhatsApp `/faq`.

## Point Meta webhook at Cloud Run

After deploy, Cloud Run gives a URL like:

```text
https://whatsapp-faq-bot-xxxxx-uc.a.run.app
```

In Meta WhatsApp → Configure Webhooks:

- Callback URL: `https://whatsapp-faq-bot-xxxxx-uc.a.run.app/webhook`
- Verify token: same as `WHATSAPP_VERIFY_TOKEN`
- Subscribe: `messages`

No more ngrok URL updates.

## How FAQ + RAG works

1. **Source of truth:** FAQ text in GCS (`FAQ_GCS_BUCKET` / `FAQ_GCS_OBJECT`), or local `data/science_olympiad_faq.txt` when the bucket env is empty.
2. **Admin UI** and WhatsApp **`/faq`** both read/write that same text.
3. On every save, the app rebuilds an **embedding index** (OpenAI `text-embedding-3-small` by default) and stores it next to the FAQ.
4. Parent questions retrieve the top-k relevant chunks, then only those excerpts are sent to the LLM — not the whole FAQ every time.

## Notes

- Without `FAQ_GCS_BUCKET`, FAQ edits on Cloud Run are ephemeral (container disk).
- If the embedding index is missing, the first question rebuilds it (or falls back to the full FAQ text).
