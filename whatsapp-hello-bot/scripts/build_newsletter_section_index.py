#!/usr/bin/env python
"""Build newsletter HTML/section embedding index (FAQ-miss safety net).

Usage (from whatsapp-hello-bot/):
  python scripts/build_newsletter_section_index.py
  python scripts/build_newsletter_section_index.py --local-only

Requires OPENAI_API_KEY for embeddings. beautifulsoup4 needed to parse
*_Source.html when *_Cleaned_Sections.md is missing
(pip install -r requirements-newsletter.txt).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.chdir(ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--issues-root",
        type=Path,
        default=None,
        help="Path to newsletter_archive/issues (default from config)",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Do not upload index to FAQ_GCS_BUCKET",
    )
    args = parser.parse_args()

    from app.config import (
        FAQ_GCS_BUCKET,
        NEWSLETTER_ISSUES_LOCAL,
        NEWSLETTER_SECTIONS_INDEX_GCS_OBJECT,
        NEWSLETTER_SECTIONS_INDEX_LOCAL,
    )
    from app.newsletter_section_rag import rebuild_section_index

    root = Path(args.issues_root) if args.issues_root else Path(NEWSLETTER_ISSUES_LOCAL)
    write_gcs = (not args.local_only) and bool(FAQ_GCS_BUCKET)
    if not args.local_only and not FAQ_GCS_BUCKET:
        print(
            "FAQ_GCS_BUCKET empty; writing local index only. "
            "Set FAQ_GCS_BUCKET=vi1234-staging-whatsapp-faq to upload.",
            file=sys.stderr,
        )

    index = rebuild_section_index(issues_root=root, write_gcs=write_gcs)
    n = len(index.get("chunks") or [])
    print(f"Issues root: {root}")
    print(f"Chunks:      {n}")
    print(f"Local index: {NEWSLETTER_SECTIONS_INDEX_LOCAL}")
    if write_gcs:
        print(
            f"GCS index:   gs://{FAQ_GCS_BUCKET}/{NEWSLETTER_SECTIONS_INDEX_GCS_OBJECT}"
        )
    print(
        "Enable in the live path with USE_NEWSLETTER_SECTION_RAG=true "
        "(still FAQ-miss only)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
