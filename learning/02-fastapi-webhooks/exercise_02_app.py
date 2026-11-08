"""Exercise 02: minimal webhook endpoints (no production deploys, no Meta sends)."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

app = FastAPI(title="Learning Webhook")

# In-memory capture for tests / local practice
RECEIVED: list[dict[str, str]] = []

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "learning-verify-token")


@app.get("/webhook")
async def verify_webhook(request: Request) -> Response:
    """Meta verify challenge.

    If hub.mode == subscribe AND hub.verify_token matches VERIFY_TOKEN,
    return hub.challenge as plain text with 200.
    Otherwise return 403.
    """
    # TODO: read query params and implement the challenge response
    raise NotImplementedError


@app.post("/webhook")
async def receive_webhook(payload: dict[str, Any]) -> dict[str, str]:
    """Parse inbound WhatsApp-like JSON and record text messages.

    Walk payload['entry'][*]['changes'][*]['value']['messages'].
    For each type==text message, append {'from': ..., 'body': ...} to RECEIVED.
    Always return {'status': 'ok'} even if parsing finds nothing.
    """
    # TODO: implement safe parsing; never call external APIs here
    raise NotImplementedError


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "learning_mode": "1"}
