# WhatsApp Hello Bot

Smallest useful WhatsApp bot for a normal group:

1. Pin a link in your WhatsApp group
2. Parents tap it → private chat with the bot opens
3. They send any first message
4. Bot replies with your greeting (default: `hello, how are you`)
5. Only you (admin) can change that greeting on a password-protected webpage

No AI yet. Fixed greeting only. This is the WhatsApp foundation for the later school-event FAQ assistant.

## Quick start (easiest path)

### Windows note

You do **not** need the Start Menu folder  
`C:\Users\...\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Python\Python 3.14`  
in this README. That folder only holds shortcuts.

Open **Command Prompt** or **PowerShell**, then check Python works:

```bat
py --version
```

If that fails, try:

```bat
python --version
```

If both fail, reinstall Python from [python.org](https://www.python.org/downloads/) and enable **“Add python.exe to PATH”**.

### 1. Install

**Windows (Command Prompt / PowerShell):**

```bat
cd whatsapp-hello-bot
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

**macOS / Linux:**

```bash
cd whatsapp-hello-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Run locally

```bat
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Health: http://127.0.0.1:8000/health
- Admin: http://127.0.0.1:8000/admin  
  Password default: `changeme` (from `.env`)

### 3. Expose a public HTTPS URL (needed for Meta webhook)

Easiest option while testing: [ngrok](https://ngrok.com/)

```bat
ngrok http 8000
```

Copy the `https://....ngrok-free.app` URL. Your webhook will be:

```text
https://YOUR-NGROK-URL/webhook
```

## Meta WhatsApp setup (keep it simple)

You do **not** need a full production business rollout for this first bot.
Use Meta’s free test number first.

### A. Create the Meta app

1. Go to [Meta for Developers](https://developers.facebook.com/)
2. Create a developer account if needed
3. **Create App** → type **Business**
4. Add the product **WhatsApp**

If Meta asks for a Business Portfolio / Business Manager, create the simplest free one and attach it. That is the only “Meta business” piece required to start.

### B. Get your test credentials

In the app → **WhatsApp → API Setup**:

1. Copy **Temporary access token** → put in `.env` as `WHATSAPP_ACCESS_TOKEN`
2. Copy **Phone number ID** → `WHATSAPP_PHONE_NUMBER_ID`
3. Note the **test WhatsApp phone number** Meta gives you (this is the bot number for now)

Also set in `.env`:

```env
WHATSAPP_VERIFY_TOKEN=my-verify-token
ADMIN_PASSWORD=changeme
SECRET_KEY=any-long-random-string
```

`WHATSAPP_VERIFY_TOKEN` is a password **you invent**. Meta will send it back when verifying your webhook.

### C. Connect the webhook

In **WhatsApp → Configuration → Webhook**:

1. Callback URL: `https://YOUR-NGROK-URL/webhook`
2. Verify token: same as `WHATSAPP_VERIFY_TOKEN`
3. Subscribe to the `messages` field

### D. Send a test message

In API Setup, add your personal WhatsApp number as a test recipient, then message the Meta test number from your phone.

Expected:

- You send anything (for example `hi`)
- Bot replies with the current greeting

## Pin the bot in your group

After you have a real bot number (test number works for people Meta allows; production number works for anyone):

1. Create a link:

```text
https://wa.me/15551234567
```

Use the bot number in international format **without** `+` or spaces.

2. Post and **pin** something like:

```text
Questions? Tap to chat with our assistant:
https://wa.me/15551234567
```

3. People tap → WhatsApp opens a private chat with the bot → they message → greeting comes back.

## Change the greeting / FAQ (admin only)

1. Open `/admin` (password: `ADMIN_PASSWORD`)
2. Greeting editor is on `/admin`
3. FAQ editor is on `/admin/faq` — always shows the latest durable FAQ, including WhatsApp `/faq` adds

On Cloud Run, set `FAQ_GCS_BUCKET` so FAQ edits survive restarts (see `CLOUD_RUN.md`).

Parent questions use RAG: the FAQ is chunked + embedded; only the top matching excerpts go to the LLM.

## Phone number recommendation

| Stage | Use |
|---|---|
| Now | Meta’s free **test number** |
| Later (real parents) | A **dedicated second phone number**, not your personal WhatsApp |

Keep your personal number separate. When you move to production, register that dedicated number in WhatsApp Cloud API.

## Project layout

```text
whatsapp-hello-bot/
  app/
    main.py           # webhook + admin routes
    faq_store.py      # durable FAQ (local or GCS)
    faq_rag.py        # chunk / embed / retrieve
    faq_service.py    # answer via retrieved excerpts
    faq_admin.py      # WhatsApp /faq command
    templates/admin.html
    templates/admin_faq.html
  data/science_olympiad_faq.txt
  CLOUD_RUN.md
  .env.example
  requirements.txt
```

## What this intentionally does NOT include yet

- Managed vector DB product (Pinecone / Vertex Vector Search) — uses OpenAI embeddings + stored index JSON for now
- Multi-event dashboard / school multi-tenancy

## Troubleshooting

- **Webhook verify fails**: `.env` `WHATSAPP_VERIFY_TOKEN` must exactly match Meta’s verify token field; server must be publicly reachable over HTTPS.
- **No reply**: check server logs; confirm `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID`; confirm your personal number is on the Meta allow-list for the test number.
- **Token expired**: temporary Meta tokens expire; generate a new one in API Setup and update `.env`.
- **FAQ edits disappear on Cloud Run**: set `FAQ_GCS_BUCKET` and grant the Cloud Run service account `roles/storage.objectAdmin` (see `CLOUD_RUN.md`).
