# 02 — FastAPI webhooks

## What production does

Meta calls your app in two ways:

1. `GET /webhook` — subscription verify challenge (`hub.mode`, `hub.verify_token`, `hub.challenge`)
2. `POST /webhook` — inbound message JSON; app replies via WhatsApp Cloud API

Production always returns quickly from POST so Meta does not disable the webhook.

## Production files to read

- `whatsapp-hello-bot/app/main.py` — `verify_webhook`, `receive_webhook`
- `whatsapp-hello-bot/app/whatsapp.py` — outbound send helper
- `whatsapp-hello-bot/app/config.py` — `WHATSAPP_VERIFY_TOKEN`

## Your exercise

Implement a tiny FastAPI app in `exercise_02_app.py` with:

- `GET /webhook` verify logic using env `WHATSAPP_VERIFY_TOKEN` (default `learning-verify-token`)
- `POST /webhook` that extracts the first text message body + `from` phone and appends it to an in-memory list (no real Meta calls)

Run tests:

```powershell
cd learning
.\.venv\Scripts\python.exe -m pytest 02-fastapi-webhooks -q
```

Optional manual run:

```powershell
.\.venv\Scripts\uvicorn.exe exercise_02_app:app --app-dir 02-fastapi-webhooks --port 8091
```

## Compare afterward

Notice production also branches on help / opener / `/faq` / normal FAQ after parsing the text.
