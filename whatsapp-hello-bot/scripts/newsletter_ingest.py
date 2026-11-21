#!/usr/bin/env python
"""CLI: newsletter-ingest

Usage (from whatsapp-hello-bot/ with venv active):

    python scripts/newsletter_ingest.py --query "subject:(Crone newsletter)" --dry-run
    python scripts/newsletter_ingest.py --label "Crone Newsletter" --confirm
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from newsletter_archive.cli import cmd_ingest

if __name__ == "__main__":
    raise SystemExit(cmd_ingest())
