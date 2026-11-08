"""Exercise 01: pure helpers used by the WhatsApp bot.

Implement these yourself. Do not copy-paste production code first.
"""

from __future__ import annotations

import re


def normalize_phone(phone: str) -> str:
    """Return digits only from a phone string.

    Examples:
      '+1 (812) 216-5774' -> '18122165774'
      '  ' -> ''
    """
    # TODO: remove every non-digit character and return the result
    raise NotImplementedError


def is_help_command(text: str) -> bool:
    """True for help/menu/start style commands (case-insensitive)."""
    # TODO: treat these as help: help, /help, menu, /menu, start
    raise NotImplementedError


def is_opener_message(text: str) -> bool:
    """True for short greetings or 'I have a question about ...' openers.

    Production also treats empty text as an opener.
    """
    # TODO:
    # 1) empty / whitespace-only => True
    # 2) hi/hello/hey => True
    # 3) text starting with 'i have a question about' => True
    raise NotImplementedError


def build_wa_me_link(bot_phone: str, prefill_text: str) -> str | None:
    """Build https://wa.me/<digits>?text=<urlencoded> or None if no phone."""
    # TODO: normalize phone; if empty return None; URL-encode prefill with urllib.parse.quote
    raise NotImplementedError
