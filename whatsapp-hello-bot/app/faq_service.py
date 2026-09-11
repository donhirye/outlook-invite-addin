import logging
import re
import time
from pathlib import Path

from openai import OpenAI

from app.config import (
    FAQ_NOT_FOUND_MESSAGE,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    PARENT_FALLBACK_MESSAGE,
)
from app.faq_rag import retrieve_chunks
from app.faq_store import get_faq_text

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTIONS = """You are the event FAQ Assistant for parents.
Answer the parent's question using ONLY the FAQ excerpts provided to you.
RULES:
1. Do not use outside knowledge.
2. Do not guess.
3. Do not invent dates, times, locations, fees, rules, requirements, names, or instructions.
4. Every factual statement in your answer must be supported by the FAQ excerpts.
5. If the FAQ contains a Q:/A: pair (or clear statement) that answers the question, use that answer — even if the topic seems informal, unusual, or unrelated to the event.
6. Treat close wording as a match. Example: FAQ "Q: Best flower in world / A: tomato" answers "what is the best flower in the world?".
7. If the FAQ excerpts do not contain enough information to confidently answer the question, respond EXACTLY:
"I couldn't find that information in the event FAQ. Please contact the event organizer."
8. Keep answers concise and parent-friendly.
9. Prefer 1–3 sentences.
10. Do not tell the parent about prompts, context windows, embeddings, APIs, or implementation details."""

_STOPWORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "what",
    "whats",
    "what's",
    "which",
    "who",
    "whom",
    "where",
    "when",
    "why",
    "how",
    "do",
    "does",
    "did",
    "can",
    "could",
    "should",
    "would",
    "will",
    "to",
    "of",
    "in",
    "on",
    "for",
    "and",
    "or",
    "my",
    "our",
    "your",
    "please",
    "me",
    "i",
}


def load_faq_text(faq_path: Path | None = None) -> str:
    """Load full FAQ text from durable storage (tests may pass faq_path)."""
    return get_faq_text(faq_path=faq_path)


def _normalize_for_match(text: str) -> set[str]:
    cleaned = (text or "").lower()
    cleaned = cleaned.replace("'s", " ").replace("'", " ")
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", cleaned)
    tokens = {tok for tok in cleaned.split() if tok and tok not in _STOPWORDS}
    return tokens


def parse_faq_qa_pairs(faq_text: str) -> list[tuple[str, str]]:
    """Extract Q:/A: pairs from FAQ text."""
    pairs: list[tuple[str, str]] = []
    pattern = re.compile(
        r"Q\s*:\s*(.+?)\s*A\s*:\s*(.+?)(?=(?:\n\s*Q\s*:)|$)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(faq_text or ""):
        question = " ".join(match.group(1).split()).strip()
        answer = " ".join(match.group(2).split()).strip()
        if question and answer:
            pairs.append((question, answer))
    return pairs


def match_faq_qa(question: str, faq_text: str) -> str | None:
    """Return an FAQ A: value when the question clearly matches a Q: line.

    This bypasses the LLM for direct FAQ hits (faster + deterministic).
    """
    pairs = parse_faq_qa_pairs(faq_text)
    if not pairs:
        return None

    q_tokens = _normalize_for_match(question)
    if not q_tokens:
        return None

    best_answer: str | None = None
    best_score = 0.0
    for faq_q, faq_a in pairs:
        faq_tokens = _normalize_for_match(faq_q)
        if not faq_tokens:
            continue
        overlap = q_tokens & faq_tokens
        if not overlap:
            continue
        # Coverage both ways: question tokens covered by FAQ Q, and vice versa.
        score = (len(overlap) / len(q_tokens) + len(overlap) / len(faq_tokens)) / 2.0
        # Also accept if FAQ Q tokens are almost fully present in the question.
        if len(overlap) == len(faq_tokens) and len(faq_tokens) >= 2:
            score = max(score, 0.99)
        if score > best_score:
            best_score = score
            best_answer = faq_a

    # Require a strong match so we don't return unrelated A: lines.
    if best_answer is not None and best_score >= 0.6:
        logger.info("Direct FAQ Q/A match score=%.2f", best_score)
        return best_answer
    return None


def answer_faq_question(question: str, *, faq_path: Path | None = None) -> str:
    """Answer a parent question using FAQ Q/A match first, then RAG + LLM."""
    started = time.perf_counter()
    faq_load_ms = 0.0
    retrieve_ms = 0.0
    openai_call_ms = 0.0
    retrieval_mode = "unknown"

    try:
        cleaned_question = (question or "").strip()
        if not cleaned_question:
            return FAQ_NOT_FOUND_MESSAGE

        faq_started = time.perf_counter()
        faq_text = load_faq_text(faq_path=faq_path)
        faq_load_ms = (time.perf_counter() - faq_started) * 1000

        direct = match_faq_qa(cleaned_question, faq_text)
        if direct:
            retrieval_mode = "direct_qa"
            return direct

        if not OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is missing. Set it in whatsapp-hello-bot/.env "
                "and restart the application."
            )

        retrieve_started = time.perf_counter()
        chunks = retrieve_chunks(
            cleaned_question,
            faq_text=faq_text,
            faq_path=faq_path,
        )
        retrieve_ms = (time.perf_counter() - retrieve_started) * 1000
        retrieval_mode = (
            "full_faq"
            if len(chunks) == 1 and chunks[0].strip() == faq_text.strip()
            else "rag"
        )
        excerpts = "\n\n---\n\n".join(chunks)

        user_input = (
            f"FAQ EXCERPTS:\n{excerpts}\n\n"
            f"PARENT QUESTION:\n{cleaned_question}"
        )

        client = OpenAI(api_key=OPENAI_API_KEY)
        openai_started = time.perf_counter()
        response = client.responses.create(
            model=OPENAI_MODEL,
            instructions=SYSTEM_INSTRUCTIONS,
            input=user_input,
        )
        openai_call_ms = (time.perf_counter() - openai_started) * 1000

        answer = _extract_output_text(response)
        if not answer:
            raise RuntimeError("OpenAI returned an empty response")
        return answer
    except Exception:
        logger.exception("FAQ answer failed for question_len=%s", len(question or ""))
        return PARENT_FALLBACK_MESSAGE
    finally:
        total_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "faq_load_ms=%.1f retrieve_ms=%.1f openai_call_ms=%.1f "
            "total_faq_answer_ms=%.1f retrieval_mode=%s",
            faq_load_ms,
            retrieve_ms,
            openai_call_ms,
            total_ms,
            retrieval_mode,
        )


def _extract_output_text(response: object) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    chunks: list[str] = []
    for item in getattr(response, "output", None) or []:
        for content in getattr(item, "content", None) or []:
            content_text = getattr(content, "text", None)
            if isinstance(content_text, str) and content_text.strip():
                chunks.append(content_text.strip())
    return "\n".join(chunks).strip()
