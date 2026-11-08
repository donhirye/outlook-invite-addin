# 01 — Python basics from the bot

## What production does

The WhatsApp bot uses small pure functions to:

- strip a phone number down to digits (`normalize_phone`)
- decide if a message is just an opener/greeting (`is_opener_message`)
- decide if someone is asking for help (`is_help_command`)

These run **before** any FAQ or LLM call.

## Production files to read

- `whatsapp-hello-bot/app/faq_admin.py` — `normalize_phone`, `is_opener_message`, `is_help_command`
- `whatsapp-hello-bot/app/event_link_store.py` — `_normalize_phone`, `build_wa_me_link`

## Your exercise

Implement the TODOs in `exercise_01.py`, then run:

```powershell
cd learning
.\.venv\Scripts\python.exe -m pytest 01-python-basics -q
```

## Compare afterward

Open the production functions and note where your version differs (regex vs loops, case handling, opener patterns).
