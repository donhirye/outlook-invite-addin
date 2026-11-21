"""Normalize newsletter/FAQ text so Excel and WhatsApp don't show mojibake junk.

Common case: UTF-8 curly quotes / en-dashes mis-decoded as Windows-1252 become
``â€œ`` / ``â€`` / ``â€“``. We also flatten remaining smart punctuation to ASCII.
"""

from __future__ import annotations

import re

# Already-corrupted UTF-8→cp1252 sequences seen in FAQ CSVs / Excel.
# Order matters: longer / more specific sequences first.
_MOJIBAKE = (
    ("â€œ", '"'),
    ("â€\x9d", '"'),
    ("â€", '"'),
    ("â€˜", "'"),
    ("â€™", "'"),
    ("â€“", "-"),
    ("â€”", "-"),
    ("â€’", "-"),
    ("â€¦", "..."),
    ("Ã¢â‚¬Å“", '"'),
    ("Ã¢â‚¬Â\x9d", '"'),
    ("Â\xa0", " "),
    ("Â ", " "),
)

_SMART = str.maketrans(
    {
        "\u201c": '"',  # “
        "\u201d": '"',  # ”
        "\u2018": "'",  # ‘
        "\u2019": "'",  # ’
        "\u2013": "-",  # –
        "\u2014": "-",  # —
        "\u2015": "-",  # ―
        "\u2012": "-",  # ‒
        "\u2010": "-",  # ‐
        "\u2212": "-",  # −
        "\u00a0": " ",  # nbsp
        "\u200b": "",  # zero-width space
        "\u200c": "",  # zwnj (Smore filler)
        "\u200d": "",
        "\ufeff": "",
        "\u00ad": "",  # soft hyphen
    }
)

# Truncated closing-quote mojibake often appears as bare ``â€`` (final byte lost).
_TRUNCATED_QUOTE = re.compile(r"â€[\x9d]?")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")


def clean_faq_text(text: str) -> str:
    """Return ASCII-friendly text safe for CSV / Excel / WhatsApp."""
    if not text:
        return ""
    out = text
    for bad, good in _MOJIBAKE:
        out = out.replace(bad, good)
    out = out.translate(_SMART)
    # Leftover quote tails → straight "; do this before deleting other junk.
    out = _TRUNCATED_QUOTE.sub('"', out)
    out = out.replace("Â", "")
    out = _MULTI_SPACE.sub(" ", out)
    return out.strip()
