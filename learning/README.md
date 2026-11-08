# Learning workspace

This folder is a **separate practice area** for understanding the production WhatsApp bot in `whatsapp-hello-bot/`.

It is not a second production app.

## Goals

- Re-implement the important ideas yourself (Python, FastAPI webhooks, FAQ/RAG, agent-style tool use)
- Run small exercises locally with mock data
- Keep production Cloud Run / GCS FAQ data untouched

## Safety rules

- Use only the `learning/` virtualenv (`learning/.venv`)
- Do **not** run `gcloud run deploy` from here
- Do **not** set real `FAQ_GCS_BUCKET` or production tokens in learning exercises
- Private WhatsApp CSVs stay in `learning/data/` and are gitignored

## Setup

```powershell
cd C:\Users\mihir\Projects\outlook-invite-addin\learning
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Modules

| Folder | Focus | Production counterparts |
|---|---|---|
| `01-python-basics/` | strings, parsing, pure functions | `app/faq_admin.py`, `app/event_link_store.py` |
| `02-fastapi-webhooks/` | HTTP verify + inbound JSON | `app/main.py` webhook routes |
| `03-faq-retrieval/` | FAQ match + tiny RAG | `app/faq_service.py`, `app/faq_rag.py` |
| `04-agent-tools/` | tool calling / agent loop | how the bot chooses help vs FAQ vs `/faq` |

Track your notes in `learnings.md`.

## Relocated personal files

| Original | New location |
|---|---|
| `whatsapp-hello-bot/learnings.txt` | preserved in `learnings.md` + `data/learnings.txt.original` |
| `whatsapp-hello-bot/playground/temptemp.py` | `playground/temptemp.py` (+ `.original` backup) |
| `.../crone_full_message_classification_with_senders.csv` | `data/` (**gitignored**) |
