"""CLI entrypoints for newsletter archive workflows."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _add_verbose(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-v", "--verbose", action="store_true")


def cmd_ingest(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="newsletter-ingest",
        description=(
            "Ingest Crone PTSA newsletters from Gmail into an immutable archive "
            "(local + optional Google Drive). Never fetches Smore to rebuild content."
        ),
    )
    parser.add_argument(
        "--query",
        help="Gmail search query (configurable; do not hard-code sender/subject in code).",
    )
    parser.add_argument(
        "--label",
        help="Gmail label name or 'label:Name' operator.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview matches only (default if --confirm is not passed).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Write local archive and upload source files to Drive (requires config).",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="With --confirm: write local archive only (skip Drive). Useful before OAuth Drive is ready.",
    )
    parser.add_argument("--max-results", type=int, default=500)
    parser.add_argument(
        "--drive-parent-folder-id",
        help="Override NEWSLETTER_DRIVE_PARENT_FOLDER_ID for this run.",
    )
    _add_verbose(parser)
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    if args.dry_run and args.confirm:
        print("Pass either --dry-run or --confirm, not both.", file=sys.stderr)
        return 2
    if args.local_only and not args.confirm:
        print("--local-only requires --confirm.", file=sys.stderr)
        return 2

    # Default to dry-run when --confirm is not set.
    dry_run = not args.confirm
    if dry_run:
        print("No --confirm given; running dry-run preview.")

    from newsletter_archive.ingest import run_ingest

    run_ingest(
        query=args.query,
        label=args.label,
        dry_run=dry_run,
        confirm=bool(args.confirm),
        max_results=args.max_results,
        drive_parent_folder_id=args.drive_parent_folder_id,
        write_local_only=bool(args.local_only),
    )
    return 0


def cmd_generate_sections(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="newsletter-generate-sections",
        description="Build Cleaned_Sections.md from an archived issue folder (no network).",
    )
    parser.add_argument("issue_folder", type=Path)
    _add_verbose(parser)
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    from newsletter_archive.generate import generate_sections

    path = generate_sections(args.issue_folder)
    print(path)
    return 0


def cmd_generate_faq(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="newsletter-generate-faq",
        description=(
            "Build FAQ.csv draft from an archived issue using the canonical LLM "
            "extractor rules. Writes FAQ_Review.md alongside. Use --heuristic for "
            "the offline section-based extractor (no OpenAI)."
        ),
    )
    parser.add_argument("issue_folder", type=Path)
    parser.add_argument(
        "--heuristic",
        action="store_true",
        help="Use offline section heuristics instead of the LLM extractor.",
    )
    parser.add_argument(
        "--model",
        help="Override OPENAI_MODEL for this run (LLM mode only).",
    )
    _add_verbose(parser)
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    from newsletter_archive.generate import generate_faq

    csv_path, review_path = generate_faq(
        args.issue_folder,
        heuristic=bool(args.heuristic),
        model=args.model,
    )
    print(csv_path)
    if review_path:
        print(review_path)
    return 0


def cmd_reconcile_faq(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="newsletter-reconcile-faq",
        description=(
            "Reconcile candidate newsletter FAQ CSVs into combined_FAQ.csv "
            "(sibling of the issues/ folder) using the canonical reconciler rules."
        ),
    )
    parser.add_argument(
        "candidate_csvs",
        nargs="+",
        type=Path,
        help="Candidate *_FAQ.csv paths, applied in the order given.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Start from an empty canonical set (ignore any existing combined_FAQ.csv).",
    )
    parser.add_argument(
        "--continue",
        dest="continue_existing",
        action="store_true",
        help="Load existing combined_FAQ.csv and append/reconcile onto it.",
    )
    parser.add_argument("--model", help="Override OPENAI_MODEL for this run.")
    parser.add_argument(
        "--notes",
        default="",
        help="Optional prior human review notes for the reconciler.",
    )
    _add_verbose(parser)
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    if args.reset and args.continue_existing:
        print("Pass either --reset or --continue, not both.", file=sys.stderr)
        return 2
    # Default for this one-time workflow: reset when neither flag is set.
    reset = True if not args.continue_existing else False
    if args.reset:
        reset = True

    from newsletter_archive.faq_reconcile import reconcile_candidates_sequential

    csv_path, report_path, rows = reconcile_candidates_sequential(
        list(args.candidate_csvs),
        reset=reset,
        model=args.model,
        prior_notes=args.notes or "",
    )
    print(csv_path)
    print(report_path)
    print(f"rows={len(rows)}")
    return 0


def cmd_generate_pdf(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="newsletter-generate-pdf",
        description="Build Review.pdf from an archived issue folder (no network).",
    )
    parser.add_argument("issue_folder", type=Path)
    _add_verbose(parser)
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    from newsletter_archive.generate import generate_pdf

    path = generate_pdf(args.issue_folder)
    print(path)
    return 0
