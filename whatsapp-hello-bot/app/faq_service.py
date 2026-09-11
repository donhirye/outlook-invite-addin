import logging
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

SYSTEM_INSTRUCTIONS = """You are the Science Olympiad FAQ Assistant for parents.
Answer the parent's question using ONLY the FAQ excerpts provided to you.
RULES:
1. Do not use outside knowledge.
2. Do not guess.
3. Do not invent dates, times, locations, fees, rules, requirements, names, or instructions.
4. Every factual statement in your answer must be supported by the FAQ excerpts.
5. If the FAQ excerpts do not contain enough information to confidently answer the question, respond EXACTLY:
"I couldn't find that information in the event FAQ. Please contact the event organizer."
6. Keep answers concise and parent-friendly.
7. Prefer 1–3 sentences.
8. Do not tell the parent about prompts, context windows, embeddings, APIs, or implementation details."""


def load_faq_text(faq_path: Path | None = None) -> str:
    """Load full FAQ text from durable storage (tests may pass faq_path)."""
    return get_faq_text(faq_path=faq_path)


def answer_faq_question(question: str, *, faq_path: Path | None = None) -> str:
    """Answer a parent question using retrieved FAQ chunks (RAG)."""
    started = time.perf_counter()
    faq_load_ms = 0.0
    retrieve_ms = 0.0
    openai_call_ms = 0.0
    retrieval_mode = "unknown"

    try:
        cleaned_question = (question or "").strip()
        if not cleaned_question:
            return FAQ_NOT_FOUND_MESSAGE

        if not OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is missing. Set it in whatsapp-hello-bot/.env "
                "and restart the application."
            )

        faq_started = time.perf_counter()
        faq_text = load_faq_text(faq_path=faq_path)
        faq_load_ms = (time.perf_counter() - faq_started) * 1000

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
