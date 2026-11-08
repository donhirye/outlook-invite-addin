"""Exercise 03: FAQ parse/match + tiny lexical retrieval (no OpenAI)."""

from __future__ import annotations

import re
from pathlib import Path

SAMPLE_FAQ = Path(__file__).resolve().parents[1] / "data" / "sample_faq.txt"


def load_faq(path: Path | None = None) -> str:
    target = path or SAMPLE_FAQ
    return target.read_text(encoding="utf-8")


def parse_faq_qa_pairs(faq_text: str) -> list[tuple[str, str]]:
    """Extract (question, answer) pairs from lines like Q: ... A: ..."""
    # TODO: find Q:/A: pairs. Keep it simple; production uses a regex.
    raise NotImplementedError


def match_faq_qa(question: str, faq_text: str) -> str | None:
    """If the user question overlaps strongly with a FAQ Q, return that A."""
    # TODO: compare normalized tokens; return best answer or None
    raise NotImplementedError


def chunk_faq_text(text: str, max_chars: int = 200) -> list[str]:
    """Split FAQ text into small chunks for retrieval practice."""
    # TODO: split on blank lines first; if a block is huge, hard-wrap by max_chars
    raise NotImplementedError


def retrieve_chunks(question: str, chunks: list[str], top_k: int = 2) -> list[str]:
    """Return top_k chunks by simple token-overlap score."""
    # TODO: score each chunk by shared lowercase word count with the question
    raise NotImplementedError


def answer_from_faq(question: str, faq_text: str | None = None) -> str:
    """Prefer exact Q/A match; else join retrieved chunks as a pseudo-answer."""
    text = faq_text if faq_text is not None else load_faq()
    direct = match_faq_qa(question, text)
    if direct:
        return direct
    chunks = chunk_faq_text(text)
    top = retrieve_chunks(question, chunks, top_k=2)
    if not top:
        return "I couldn't find that information in the event FAQ."
    return "\n\n".join(top)
