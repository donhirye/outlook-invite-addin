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

gcloud config set project $PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

## Deploy

From `whatsapp-hello-bot/`:

```bash
gcloud run deploy $SERVICE_NAME \
  --source . \
  --region $REGION \
  --allow-unauthenticated \
  --set-env-vars "WHATSAPP_VERIFY_TOKEN=my-verify-token,WHATSAPP_PHONE_NUMBER_ID=YOUR_PHONE_ID,OPENAI_MODEL=gpt-5.6-luna,FAQ_ADMIN_PHONES=18122165774,ADMIN_PASSWORD=changeme,SECRET_KEY=long-random-string"
```

Then set sensitive env vars in Cloud Run console (or Secret Manager):

- `WHATSAPP_ACCESS_TOKEN`
- `OPENAI_API_KEY`

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

## Notes

- FAQ file is baked into the container from `data/science_olympiad_faq.txt`
- `/faq` admin adds entries to the container filesystem (ephemeral unless you add a volume/bucket later)
- For durable FAQ edits on Cloud Run, next step is Cloud Storage or a DB
