# WhatsApp Hello World — The Frustrating Journey

A hard-won record of what it took to get a tiny WhatsApp bot working:

> Parent taps a link / messages the bot → bot replies with a greeting.

This is **not** the FAQ/RAG product yet. This is only the WhatsApp hello-bot foundation.

---

## What we set out to build

1. A normal WhatsApp group gets a **pinned link**
2. People tap it → private chat with the bot opens
3. They send any first message (e.g. `Hi`)
4. Bot replies with a configurable greeting (default: `hello, how are you`)
5. Only an admin can change that greeting via a password-protected webpage
6. Later: FAQ/RAG pipeline for school events (not built in this phase)

### Important reality checks learned early

- Official WhatsApp does **not** support a true “pinned AI bot inside a group” like Discord/Telegram.
- Realistic UX: pin a `https://wa.me/<BOT_NUMBER>` link → opens **1:1 chat** with the bot.
- WhatsApp does **not** notify your server when someone only opens the chat.
  The greeting fires on the **first inbound message**.
- Use a **dedicated bot number** (Meta test number first), not your personal WhatsApp.

---

## Final working architecture

```text
Parent phone (WhatsApp)
        │
        ▼
Meta WhatsApp Cloud API
        │
        ▼
ngrok public HTTPS URL  ──►  local FastAPI (uvicorn :8001)
        │
        ├── GET  /webhook   (Meta verify challenge)
        ├── POST /webhook   (inbound messages)
        ├── GET  /admin     (password-protected greeting editor)
        └── GET  /health
        │
        ▼
Graph API send message
        │
        ▼
Parent phone sees greeting
```

Code lives in:

```text
whatsapp-hello-bot/
```

---

## Step-by-step: everything we actually did

### 1. Build the local bot app

Created `whatsapp-hello-bot/` with:

- FastAPI webhook (`/webhook`)
- Admin page (`/admin`) to edit greeting
- Greeting stored in `data/greeting.json`
- `.env` for secrets
- README + tests

Default greeting: `hello, how are you`

Admin password via `.env`: `ADMIN_PASSWORD=changeme`

---

### 2. Run it on Windows (pain #1)

Wrong assumptions burned time:

- Start Menu path  
  `...\Start Menu\Programs\Python\Python 3.14`  
  is **shortcuts**, not the install path.
- Unix commands fail on Windows.

Working Windows flow:

```bat
cd whatsapp-hello-bot
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Also learned:

- Don’t recreate `.venv` while it is already activated.
- Clone the real repo (`outlook-invite-addin/whatsapp-hello-bot`), not an unrelated local `whatsapp-bot` folder full of old scripts.
- Port `8000` was haunted by ghost listeners on this machine → use **`8001`**.

---

### 3. Expose localhost with ngrok (pain #2)

Meta needs a public HTTPS webhook.

Problems hit:

- ngrok not authenticated → need `ngrok config add-authtoken <token>`
- ngrok agent too old → update/reinstall
- Chocolatey update blocked / McAfee blocked downloads
- Literal placeholder mistakes (`YOUR_NEW_TOKEN`, `your-current-ngrok`)

Working pattern:

```bat
ngrok http 8001
```

Then verify:

```text
https://<current-ngrok-subdomain>.ngrok-free.app/health
→ {"status":"ok"}
```

**Critical lesson:** every ngrok restart creates a **new URL**. Meta webhook must be updated + re-verified.

---

### 4. Create the Meta app / WhatsApp product (pain #3)

High-level Meta path:

1. [developers.facebook.com](https://developers.facebook.com/) → Create App
2. Create/connect a Business Portfolio (“Mihir Inc”)
3. Add WhatsApp use case: **Connect with customers through WhatsApp**
4. Use **Step 1. Try it out** for test number + token + recipient allowlist
5. Use **Step 2. Production setup → Configure Webhooks** for callback URL

Useful IDs from this journey:

| Thing | Value used |
|---|---|
| App | `school hello bot` |
| App ID | `3710600342421547` |
| Phone Number ID | `1233715439834301` |
| Test display number | `+1 555-203-2022` |
| Personal allowlisted recipient | `+1 812-216-5774` |
| WABA ID | `1064649393193634` |
| WABA name | Test WhatsApp Business Account |

---

### 5. Configure `.env`

Required keys:

```env
ADMIN_PASSWORD=changeme
SECRET_KEY=change-me-to-a-long-random-string
WHATSAPP_VERIFY_TOKEN=my-verify-token
WHATSAPP_ACCESS_TOKEN=<token from Meta>
WHATSAPP_PHONE_NUMBER_ID=1233715439834301
GRAPH_API_VERSION=v21.0
```

Lessons:

- File must be named **`.env`**, not only `.env.example`
- Exact key names matter
- Restart uvicorn after changing `.env` (`--reload` does **not** reload env vars)
- Never paste access tokens into chat / commits
- Temporary tokens expire constantly → later use a System User long-lived token

---

### 6. Webhook verify token

`WHATSAPP_VERIFY_TOKEN` is **not issued by Meta**.

You invent it (we used `my-verify-token`) and put the **same value** in:

- `.env`
- Meta webhook “Verify token” field

Opening `/webhook` in a browser alone will show `Verification failed`. That is normal.  
Meta verify works only when Meta calls:

```text
GET /webhook?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
```

Also: Callback URL must include **`/webhook`**.  
Root ngrok URL alone will fail verify.

---

### 7. Publish the app (needed for real phone traffic)

While unpublished, Meta warned:

> Apps will only be able to receive test webhooks sent from the app dashboard while the app is unpublished.

Publish was blocked until we added a **Privacy Policy URL**.

We added:

- `whatsapp-hello-bot/privacy-policy.html`
- optional route `/privacy`

Then published the app successfully.

---

### 8. The errors we hit (in order) and what they meant

| Symptom / error | Meaning | Fix |
|---|---|---|
| `{"detail":"Not Found"}` on `/health` | Wrong process/port or wrong folder | Run bot on `8001`, confirm root text says “WhatsApp Hello Bot is running” |
| ngrok `ERR_NGROK_4018` | Not authenticated | `ngrok config add-authtoken ...` |
| ngrok version too old | Agent below account minimum | Update/reinstall ngrok |
| `ERR_NGROK_3200` endpoint offline | Old ngrok URL | Use current Forwarding URL |
| Browser `/webhook` = Verification failed | No Meta query params | Ignore; verify from Meta button |
| Callback URL missing `/webhook` | Verify fails | Append `/webhook` |
| `credentials missing` | Empty/unloaded token or phone id | Fix `.env`, restart uvicorn |
| `401 Unauthorized` / OAuth `190` | Expired/invalid access token | Generate new token, restart uvicorn |
| `131030` recipient not in allowed list | Sending to non-allowlisted number (dashboard test uses fake `16315551181`) | Add real phone as recipient; message from that phone |
| Dashboard Test → `POST` works, phone reply → no `POST` | Inbound WABA not subscribed to app | `POST /{WABA_ID}/subscribed_apps` |
| Graph `whatsapp_business_account` field missing / `subscribed_apps` on phone id fails | Wrong object for that call | Use WABA ID `1064649393193634`, not phone number id |

---

### 9. The final missing piece (the breakthrough)

Webhook URL + publish + token were still not enough for phone inbound.

Dashboard **Test** on `messages` produced `POST /webhook`.  
Real WhatsApp `Hi` did **not**.

Fix:

1. Find WABA ID in Business Settings → WhatsApp accounts  
   → `1064649393193634`
2. Graph API Explorer:

```text
POST /1064649393193634/subscribed_apps
```

3. Response:

```json
{"success": true}
```

After that, phone messages finally hit uvicorn and the bot replied.

---

## End-to-end “it works” checklist

Keep both running:

```bat
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
ngrok http 8001
```

Meta webhook:

```text
Callback URL = https://<current-ngrok>.ngrok-free.app/webhook
Verify token = my-verify-token
messages = subscribed
```

WABA subscribed:

```text
POST /1064649393193634/subscribed_apps → {"success": true}
```

Phone test:

1. From allowlisted phone `+1 812-216-5774`
2. Chat with Meta test number `+1 555-203-2022`
3. Send `Hi`
4. Uvicorn shows `POST /webhook` and reply send
5. WhatsApp shows greeting

Admin greeting edit:

```text
http://127.0.0.1:8001/admin
```

---

## Lessons learned (the short list)

1. **WhatsApp Cloud API local dev = FastAPI + ngrok + Meta**, not “install a bot on your phone.”
2. **Pinned group bot** is really a pinned `wa.me` link to a 1:1 business chat.
3. **First message triggers greeting**, not chat open.
4. **Windows setup details matter** (venv activate path, ports, correct folder).
5. **ngrok URLs are ephemeral**; re-verify webhook after every restart.
6. **Verify token is invented by you.**
7. Callback URL must end with **`/webhook`**.
8. Temporary Meta tokens expire constantly; plan for System User tokens.
9. Dashboard webhook Test ≠ real phone inbound.
10. Allowlist your personal number for test-number messaging.
11. Publishing matters for real phone webhook delivery.
12. Privacy Policy URL is required to publish.
13. The silent killer: **WABA must be subscribed to the app** via  
    `POST /{WABA_ID}/subscribed_apps`.
14. Never paste access tokens into chat.
15. Read the exact Graph/Meta error code; each one maps to a different fix.

---

## What is intentionally still not done

- Permanent/System User token setup
- Cloud Run / always-on hosting (no ngrok)
- Real production WhatsApp business number (not Meta test number)
- FAQ ingestion / RAG / LLM answers
- Multi-event organizer dashboard
- Multi-school SaaS tenancy

Those belong to later phases of the school-event FAQ assistant plan.

---

## Practical commands cheat sheet

```bat
:: bot
cd C:\Users\mihir\Projects\outlook-invite-addin\whatsapp-hello-bot
.venv\Scripts\activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001

:: tunnel
ngrok http 8001

:: sanity
curl.exe http://127.0.0.1:8001/health
```

Graph API (after token loaded in Explorer):

```text
GET  1233715439834301
POST 1064649393193634/subscribed_apps
```

---

## Bottom line

Getting “hello” working on WhatsApp was mostly **integration and Meta account plumbing**, not AI.

The bot code was the easy part.  
The hard part was:

local server → public URL → webhook verify → token freshness → allowlist → publish → **WABA subscribed_apps**.

Once that chain is complete, a phone `Hi` finally becomes a uvicorn `POST /webhook` and a WhatsApp greeting.
