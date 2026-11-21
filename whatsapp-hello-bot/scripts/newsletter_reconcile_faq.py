#!/usr/bin/env python3
"""CLI: newsletter-reconcile-faq <candidate-faq.csv> [...]"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from newsletter_archive.cli import cmd_reconcile_faq


if __name__ == "__main__":
    raise SystemExit(cmd_reconcile_faq())
