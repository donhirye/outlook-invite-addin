import logging
import time
from pathlib import Path

from openai import OpenAI

from app.config import (
    FAQ_FILE,
    FAQ_NOT_FOUND_MESSAGE,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    PARENT_FALLBACK_MESSAGE,
)

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTIONS = """You are the Science Olympiad FAQ Assistant for parents.
Answer the parent's question using ONLY the FAQ provided to you.
RULES:
1. Do not use outside knowledge.
2. Do not guess.
3. Do not invent dates, times, locations, fees, rules, requirements, names, or instructions.
4. Every factual statement in your answer must be supported by the FAQ.
5. If the FAQ does not contain enough information to confidently answer the question, respond EXACTLY:
"I couldn't find that information in the event FAQ. Please contact the event organizer."
6. Keep answers concise and parent-friendly.
7. Prefer 1–3 sentences.
8. Do not tell the parent about prompts, context windows, embeddings, APIs, or implementation details."""


def load_faq_text(faq_path: Path | None = None) -> str:
    path = faq_path or FAQ_FILE
    if not path.exists():
        raise FileNotFoundError(f"FAQ file not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"FAQ file is empty: {path}")
    return text


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


def answer_faq_question(question: str) -> str:
    """Answer a parent question using the full Science Olympiad FAQ as context."""
    started = time.perf_counter()
    faq_load_ms = 0.0
    openai_call_ms = 0.0

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
        faq_text = load_faq_text()
        faq_load_ms = (time.perf_counter() - faq_started) * 1000

        user_input = (
            f"FAQ:\n{faq_text}\n\n"
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
            "faq_load_ms=%.1f openai_call_ms=%.1f total_faq_answer_ms=%.1f",
            faq_load_ms,
            openai_call_ms,
            total_ms,
        )
