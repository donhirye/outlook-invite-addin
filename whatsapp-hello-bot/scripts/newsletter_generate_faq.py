#!/usr/bin/env python
"""CLI: newsletter-generate-faq <issue-folder>"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from newsletter_archive.cli import cmd_generate_faq

if __name__ == "__main__":
    raise SystemExit(cmd_generate_faq())
