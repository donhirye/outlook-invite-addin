import logging
from typing import Any

import httpx

from app.config import (
    GRAPH_API_VERSION,
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
)

logger = logging.getLogger(__name__)


async def _post_whatsapp(payload: dict[str, Any], *, to_phone: str) -> dict:
    if not WHATSAPP_ACCESS_TOKEN:
        logger.warning(
            "WHATSAPP_ACCESS_TOKEN is empty; skipping send to %s",
            to_phone,
        )
        return {"skipped": True, "reason": "missing_access_token"}

    if not WHATSAPP_PHONE_NUMBER_ID:
        logger.warning(
            "WHATSAPP_PHONE_NUMBER_ID is empty; skipping send to %s",
            to_phone,
        )
        return {"skipped": True, "reason": "missing_phone_number_id"}

    url = (
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
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
            logger.error(
                "WhatsApp send failed (%s) to %s via phone_number_id=%s: %s",
                response.status_code,
                to_phone,
                WHATSAPP_PHONE_NUMBER_ID,
                data,
            )
            return {
                "ok": False,
                "status_code": response.status_code,
                "error": data,
            }

        logger.info("WhatsApp send ok to %s type=%s", to_phone, payload.get("type"))
        return data


async def send_text_message(to_phone: str, body: str) -> dict:
    """Send a WhatsApp text message via Cloud API."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    return await _post_whatsapp(payload, to_phone=to_phone)


def _truncate(label: str, limit: int) -> str:
    text = (label or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


async def send_reply_buttons(
    to_phone: str,
    body: str,
    choices: list[dict[str, str]],
) -> dict:
    """Send up to 3 reply buttons. Falls back to numbered text if needed."""
    buttons = []
    for choice in (choices or [])[:3]:
        cid = _truncate(str(choice.get("id") or ""), 256)
        title = _truncate(str(choice.get("label") or cid), 20)
        if not cid or not title:
            continue
        buttons.append(
            {
                "type": "reply",
                "reply": {"id": cid, "title": title},
            }
        )
    if not buttons:
        return await send_text_message(to_phone, body)

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": _truncate(body, 1024)},
            "action": {"buttons": buttons},
        },
    }
    result = await _post_whatsapp(payload, to_phone=to_phone)
    if result.get("ok") is False or result.get("skipped"):
        return await send_text_message(to_phone, body)
    return result


async def send_list_message(
    to_phone: str,
    body: str,
    choices: list[dict[str, str]],
    *,
    button_label: str = "See options",
) -> dict:
    """Send a list message for longer choice sets."""
    rows = []
    for choice in (choices or [])[:10]:
        cid = _truncate(str(choice.get("id") or ""), 200)
        title = _truncate(str(choice.get("label") or cid), 24)
        if not cid or not title:
            continue
        rows.append({"id": cid, "title": title})
    if not rows:
        return await send_text_message(to_phone, body)

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": _truncate(body, 1024)},
            "action": {
                "button": _truncate(button_label, 20),
                "sections": [{"title": "Options", "rows": rows}],
            },
        },
    }
    result = await _post_whatsapp(payload, to_phone=to_phone)
    if result.get("ok") is False or result.get("skipped"):
        return await send_text_message(to_phone, body)
    return result


async def send_choices(
    to_phone: str,
    body: str,
    choices: list[dict[str, str]] | None,
) -> dict:
    """Prefer buttons (<=3), else list, else plain text (already numbered)."""
    if not choices:
        return await send_text_message(to_phone, body)
    if len(choices) <= 3:
        return await send_reply_buttons(to_phone, body, choices)
    return await send_list_message(to_phone, body, choices)
