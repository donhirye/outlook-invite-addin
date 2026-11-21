"""python -m newsletter_archive <ingest|sections|faq|pdf> ..."""

from __future__ import annotations

import sys

from newsletter_archive.cli import (
    cmd_generate_faq,
    cmd_generate_pdf,
    cmd_generate_sections,
    cmd_ingest,
    cmd_reconcile_faq,
)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print(
            "Usage:\n"
            "  python -m newsletter_archive ingest --query '...' --dry-run\n"
            "  python -m newsletter_archive ingest --label NAME --confirm\n"
            "  python -m newsletter_archive sections <issue-folder>\n"
            "  python -m newsletter_archive faq <issue-folder>\n"
            "  python -m newsletter_archive reconcile <candidate-faq.csv> [...]\n"
            "  python -m newsletter_archive pdf <issue-folder>\n"
        )
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd in {"ingest", "newsletter-ingest"}:
        return cmd_ingest(rest)
    if cmd in {"sections", "newsletter-generate-sections"}:
        return cmd_generate_sections(rest)
    if cmd in {"faq", "newsletter-generate-faq"}:
        return cmd_generate_faq(rest)
    if cmd in {"reconcile", "newsletter-reconcile-faq"}:
        return cmd_reconcile_faq(rest)
    if cmd in {"pdf", "newsletter-generate-pdf"}:
        return cmd_generate_pdf(rest)
    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
