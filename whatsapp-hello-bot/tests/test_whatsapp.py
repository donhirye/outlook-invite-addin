import asyncio
import os

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")

from app import whatsapp


def test_mark_as_read_with_typing_payload(monkeypatch):
    captured = {}

    async def fake_post(payload, *, to_phone):
        captured["payload"] = payload
        captured["to_phone"] = to_phone
        return {"success": True}

    monkeypatch.setattr(whatsapp, "_post_whatsapp", fake_post)
    result = asyncio.run(whatsapp.mark_as_read_with_typing("wamid.abc123"))
    assert result == {"success": True}
    assert captured["payload"] == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.abc123",
        "typing_indicator": {"type": "text"},
    }


def test_mark_as_read_with_typing_skips_empty_id():
    result = asyncio.run(whatsapp.mark_as_read_with_typing("  "))
    assert result["skipped"] is True
