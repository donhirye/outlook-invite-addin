# Launch Bot From an Existing WhatsApp Group

This MVP needs **no bot code changes**.

Your existing FastAPI + Meta webhook bot already handles private 1:1 chats.
This step only adds a **click-to-chat link** you can paste into a normal WhatsApp group.

## Flow

```text
Existing WhatsApp group
    → parent taps "Ask the Event Bot"
    → WhatsApp opens private chat with bot number
    → optional pre-filled message appears
    → parent taps Send
    → existing /webhook receives it
    → existing greeting reply is sent
```

The bot does **not** join the group.

## Click-to-chat link format

```text
https://wa.me/<BOT_NUMBER_E164_NO_PLUS>?text=<URL_ENCODED_MESSAGE>
```

For the current Meta test number `+1 555-203-2022`:

```text
https://wa.me/15552032022?text=Hi%2C%20I%20have%20a%20question%20about%20Science%20Olympiad
```

## Copy/paste group message

Paste this into your existing WhatsApp group:

```text
🤖 Questions about Science Olympiad?

Ask our Event Assistant anytime:
https://wa.me/15552032022?text=Hi%2C%20I%20have%20a%20question%20about%20Science%20Olympiad
```

Optional shorter version:

```text
Ask the Event Bot:
https://wa.me/15552032022?text=Hi%2C%20I%20have%20a%20question%20about%20Science%20Olympiad
```

## Test checklist

1. Keep uvicorn + ngrok running, webhook verified, WABA subscribed.
2. Add each tester’s WhatsApp number as a Meta **test recipient** (required for Meta test number).
3. Paste the group message above into your family/group chat.
4. From a tester phone, tap the link.
5. Confirm WhatsApp opens a private chat with `+1 555-203-2022`.
6. Send the pre-filled message.
7. Confirm uvicorn shows `POST /webhook` and the greeting arrives.

## Important limitation (current test number)

With Meta’s **test number**, only allowlisted recipients can message the bot.

That means for a family group (you, spouse, kids):

- each person’s number must be added/verified in Meta Step 1 recipient list
- otherwise the link may open, but messaging can fail

For a real school parent group later, use a production WhatsApp Business number.

## Customizing the pre-filled text

Change only the `text=` value (URL-encoded).

Example:

```text
Hi, I have a question about Field Day
→ Hi%2C%20I%20have%20a%20question%20about%20Field%20Day
```

Full link:

```text
https://wa.me/15552032022?text=Hi%2C%20I%20have%20a%20question%20about%20Field%20Day
```

## Why no code change?

Inspection result:

- Existing webhook already accepts inbound private messages
- Existing bot already replies with the configurable greeting
- `/admin` already edits that greeting
- Group launch is only a `wa.me` entry point into that same private chat

So this MVP is documentation + a copy/paste link, not a new feature in FastAPI.
