#!/usr/bin/env python
"""Build structured RAG index from combined_FAQ_latest.csv and upload to GCS.

Uploads:
  gs://<FAQ_GCS_BUCKET>/newsletter_archive/combined_FAQ_latest.csv
  gs://<FAQ_GCS_BUCKET>/newsletter_archive/combined_FAQ_latest.csv.index.json

Usage (from whatsapp-hello-bot/):
  set FAQ_GCS_BUCKET=vi1234-staging-whatsapp-faq
  python scripts/build_newsletter_faq_index.py
  python scripts/build_newsletter_faq_index.py --local-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load .env before importing app.config consumers.
os.chdir(ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Path to combined FAQ CSV (default: NEWSLETTER_COMBINED_FAQ_LOCAL)",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Write index next to the CSV only; do not upload to GCS",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=3,
        help="Print this many sample chunk records (default 3)",
    )
    args = parser.parse_args()

    from app.config import (
        FAQ_GCS_BUCKET,
        NEWSLETTER_COMBINED_FAQ_GCS_OBJECT,
        NEWSLETTER_COMBINED_FAQ_INDEX_GCS_OBJECT,
        NEWSLETTER_COMBINED_FAQ_LOCAL,
    )
    from app.faq_rag import rebuild_newsletter_combined_index

    csv_path = Path(args.csv) if args.csv else Path(NEWSLETTER_COMBINED_FAQ_LOCAL)
    write_gcs = (not args.local_only) and bool(FAQ_GCS_BUCKET)
    if not args.local_only and not FAQ_GCS_BUCKET:
        print(
            "FAQ_GCS_BUCKET is empty; writing local index only. "
            "Set FAQ_GCS_BUCKET=vi1234-staging-whatsapp-faq to upload.",
            file=sys.stderr,
        )

    index, report = rebuild_newsletter_combined_index(
        csv_path=csv_path,
        upload_csv=write_gcs,
        write_gcs=write_gcs,
    )

    print(f"CSV rows loaded via rebuild from: {csv_path}")
    print(f"Included chunks: {report.included_count}")
    print(f"Excluded rows:   {report.excluded_count}")
    for ex in report.excluded[:20]:
        print(f"  - {ex['faq_id']}: {ex['reason']}")
    if write_gcs:
        print(f"GCS CSV:   gs://{FAQ_GCS_BUCKET}/{NEWSLETTER_COMBINED_FAQ_GCS_OBJECT}")
        print(
            f"GCS index: gs://{FAQ_GCS_BUCKET}/{NEWSLETTER_COMBINED_FAQ_INDEX_GCS_OBJECT}"
        )
    else:
        print(f"Local index: {csv_path}.index.json")

    # Prefer category-boundary sample: last of one category / first of next.
    chunks = index.get("chunks") or []
    samples: list[dict] = []
    for i, ch in enumerate(chunks):
        meta = ch.get("metadata") or {}
        if i + 1 < len(chunks):
            nxt = (chunks[i + 1].get("metadata") or {}).get("category")
            if meta.get("category") and nxt and meta.get("category") != nxt:
                samples.append(ch)
                samples.append(chunks[i + 1])
                break
    if len(samples) < args.sample:
        samples = chunks[: args.sample]

    print("\nSample chunk records:")
    for ch in samples[: max(args.sample, 2)]:
        slim = {
            "id": ch.get("id"),
            "text": ch.get("text"),
            "metadata": ch.get("metadata"),
            "embedding_dims": len(ch.get("embedding") or []),
        }
        print(json.dumps(slim, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
