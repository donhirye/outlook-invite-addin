# Launch Bot From an Existing WhatsApp Group

This needs **no special group-bot join**. Parents tap a link → private 1:1 chat with the bot.

## Where each piece lives

| What parents see | Where it comes from |
|---|---|
| Prefill / “subject” like *question about Kendall 5th Grade Celebration* | The `?text=` part of the `wa.me` link you paste in the group (not the FAQ, not Cloud Run) |
| First bot intro (“I’m the PTSA chatbot…”) | Greeting text from `/admin` (or default in `data/greeting.json`) |
| Answers to real questions | Durable FAQ (`/admin/faq` or GCS) |

## Flow

```text
Existing WhatsApp group
    → parent taps the Ask-the-Bot link
    → WhatsApp opens private chat with bot number
    → pre-filled message appears (from ?text=)
    → parent taps Send
    → bot sends PTSA intro greeting
    → parent asks a real question
    → bot answers from FAQ
```

The bot does **not** join the group.

## Click-to-chat link format

```text
https://wa.me/<BOT_NUMBER_E164_NO_PLUS>?text=<URL_ENCODED_MESSAGE>
```

### Kendall 5th Grade Celebration example

Plain text:

```text
Hi, I have a question about Kendall 5th Grade Celebration
```

URL-encoded link (Meta test number example — replace with your bot number):

```text
https://wa.me/15552032022?text=Hi%2C%20I%20have%20a%20question%20about%20Kendall%205th%20Grade%20Celebration
```

### Copy/paste group message

```text
🤖 Questions about Kendall 5th Grade Celebration?

Ask our PTSA assistant:
https://wa.me/15552032022?text=Hi%2C%20I%20have%20a%20question%20about%20Kendall%205th%20Grade%20Celebration
```

## How to change the “subject line”

Only change the `text=` value (URL-encode spaces as `%20`, commas as `%2C`).

Quick encoder in PowerShell:

```powershell
[uri]::EscapeDataString("Hi, I have a question about Kendall 5th Grade Celebration")
```

Then:

```text
https://wa.me/<BOT_NUMBER>?text=<PASTE_ENCODED_STRING>
```

## Greeting / intro

Edit at: `https://YOUR-SERVICE-URL/admin`

Default intro explains:
- this is the PTSA chatbot
- answers come only from PTSA-provided FAQ info
- if unknown, ask an admin/organizer in the group

## Test checklist

1. Cloud Run (or local + ngrok) webhook is live.
2. For Meta **test** numbers, add each tester as a recipient.
3. Paste the group message above.
4. Tap the link → send the prefilled text → you should get the PTSA intro.
5. Ask a real FAQ question → you should get an FAQ answer.

## Important limitation (Meta test number)

Only allowlisted recipients can message the test number. For real parents, use a production WhatsApp Business number.
