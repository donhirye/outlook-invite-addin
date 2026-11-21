"""Deprecated one-off. Use the canonical LLM FAQ extractor instead:

  python scripts/newsletter_generate_faq.py data/newsletter_archive/issues/<issue-folder>

Rules live in newsletter_archive/extractor_prompt.py.
"""

raise SystemExit(
    "Deprecated. Run: python scripts/newsletter_generate_faq.py "
    "<issue-folder>"
)
