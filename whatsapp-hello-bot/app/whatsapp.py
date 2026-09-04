import logging

import httpx

from app.config import (
    GRAPH_API_VERSION,
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
)

logger = logging.getLogger(__name__)


async def send_text_message(to_phone: str, body: str) -> dict:
    """Send a WhatsApp text message via Cloud API."""
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logger.warning(
            "WhatsApp credentials missing; skipping send to %s: %s",
            to_phone,
            body,
        )
        return {"skipped": True, "reason": "missing_credentials"}

    url = (
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text}
        if response.status_code >= 400:
            logger.error("WhatsApp send failed: %s %s", response.status_code, data)
            response.raise_for_status()
        return data
