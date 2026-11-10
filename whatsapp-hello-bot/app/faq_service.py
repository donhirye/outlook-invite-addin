import json
import logging
import re
import time
from dataclasses import dataclass
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

# Deterministic FAQ answering (not the same thing as confidence).
FAQ_LLM_TEMPERATURE = 0

SYSTEM_INSTRUCTIONS = """You are the event FAQ Assistant for parents.
Answer the parent's question using ONLY the FAQ excerpts provided to you.
RULES:
1. Do not use outside knowledge.
2. Do not invent dates, times, locations, fees, rules, requirements, names, links, or deadlines that are not in the FAQ excerpts.
3. Every factual statement in your answer must be supported by the FAQ excerpts.
4. Prefer close wording matches. Example: FAQ "Q: Best flower in world / A: tomato" answers "what is the best flower in the world?".
5. PARTIAL ANSWERS ARE ALLOWED AND PREFERRED:
   - If the FAQ supports part of the question, answer that part clearly.
   - For any part the FAQ does not support (for example a missing deadline or order link), say that the FAQ does not include that detail and suggest contacting the school office, activity director, or PTSA Administrators as appropriate.
   - Do NOT refuse the entire question just because one detail is missing.
6. Only if the FAQ excerpts support essentially none of the question, set answer to EXACTLY:
"I couldn't find that information in the event FAQ. Please contact the PTSA Administrators."
7. Keep answers concise and parent-friendly (1–4 sentences).
8. Do not mention prompts, embeddings, APIs, or implementation details.
9. Do NOT add a "Source:" line (or rename/paraphrase a source). The system attaches the Source column from the FAQ file.
10. Respond with JSON only, no markdown fences:
{"answer":"<parent-facing answer>","confidence":<number from 0 to 1>}
confidence is how sure you are that the FAQ excerpts support the parts you did answer (1=strong support, 0=no support)."""

_SOURCE_VALUE_RE = re.compile(
    r"(?im)(?:^|\(|;\s*)source\s*:\s*([^;\n\)]+)"
)
_URL_VALUE_RE = re.compile(r"(?im)(?:^|\(|;\s*)url\s*:\s*([^;\n\)]+)")
_STRIP_SOURCE_RE = re.compile(r"(?im)^\s*source\s*:.*$")


@dataclass
class FaqAnswer:
    answer: str
    confidence: float | None = None
    match_score: float | None = None
    retrieval_mode: str = "unknown"
    llm_invocations: int = 0
    faq_id: str | None = None
    source_name: str | None = None
    source_url: str | None = None

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


def _wants_upcoming(question: str) -> bool:
    cleaned = (question or "").lower()
    return bool(
        re.search(
            r"\b(next|upcoming|this week|tomorrow|most recent announcement)\b",
            cleaned,
        )
    )


def strip_source_lines(answer: str) -> str:
    """Remove any Source: lines the model may have invented."""
    without = _STRIP_SOURCE_RE.sub("", answer or "")
    return re.sub(r"\n{3,}", "\n\n", without).strip()


def _clean_source(value: str | None) -> str | None:
    cleaned = " ".join((value or "").split()).strip()
    return cleaned or None


def extract_sources_from_text(text: str) -> list[str]:
    """Return Source: values found in FAQ text (standalone or parenthetical)."""
    found: list[str] = []
    for match in _SOURCE_VALUE_RE.finditer(text or ""):
        source = _clean_source(match.group(1))
        if source:
            found.append(source)
    return found


def extract_url_from_text(text: str) -> str | None:
    match = _URL_VALUE_RE.search(text or "")
    if not match:
        return None
    return _clean_source(match.group(1))


def resolve_source(
    faq_text: str, excerpts: str | None = None
) -> tuple[str | None, str | None]:
    """Pick Source (+ optional URL) from FAQ file text.

    Preference:
    1) Source lines inside the retrieved excerpts
    2) A single unique Source across the whole FAQ file
    3) Otherwise omit (do not invent)
    """
    excerpt_sources = extract_sources_from_text(excerpts or "")
    if excerpt_sources:
        name = excerpt_sources[-1]
        return name, extract_url_from_text(excerpts or "")
    all_sources = extract_sources_from_text(faq_text)
    unique = list(dict.fromkeys(all_sources))
    if len(unique) == 1:
        return unique[0], extract_url_from_text(faq_text)
    return None, None


def _best_faq_record(question: str) -> tuple[dict | None, float]:
    """Best structured FAQ record and score (no direct-match threshold)."""
    from app.faq_records import chicago_today, list_records
    from datetime import datetime

    records = list_records(include_inactive=False)
    if not records:
        return None, 0.0
    q_tokens = _normalize_for_match(question)
    if not q_tokens:
        return None, 0.0
    today = chicago_today()
    upcoming = _wants_upcoming(question)
    best_rec = None
    best_score = 0.0
    for rec in records:
        faq_tokens = _normalize_for_match(rec.get("question") or "")
        if not faq_tokens:
            continue
        overlap = q_tokens & faq_tokens
        if not overlap:
            continue
        score = (len(overlap) / len(q_tokens) + len(overlap) / len(faq_tokens)) / 2.0
        if len(overlap) == len(faq_tokens) and len(faq_tokens) >= 2:
            score = max(score, 0.99)
        event_raw = (rec.get("event_date") or "").strip()
        if upcoming and event_raw:
            try:
                event_day = datetime.strptime(event_raw[:10], "%Y-%m-%d").date()
                if event_day < today:
                    score *= 0.35  # demote past events for "next/upcoming" asks
                else:
                    score = min(1.0, score + 0.08)
            except ValueError:
                pass
        if score > best_score:
            best_score = score
            best_rec = rec
    return best_rec, round(best_score, 3)


def score_faq_records(question: str) -> tuple[dict | None, float]:
    """Best structured FAQ record and keyword score (thresholded for direct Q/A)."""
    best_rec, best_score = _best_faq_record(question)
    if best_rec is not None and best_score >= 0.6:
        logger.info(
            "Direct FAQ record match id=%s score=%.2f",
            best_rec.get("faq_id"),
            best_score,
        )
        return best_rec, best_score
    return None, best_score


def score_faq_qa(question: str, faq_text: str) -> tuple[str | None, float]:
    """Best FAQ A: and keyword overlap score (0–1). Answer is None if below threshold."""
    rec, score = score_faq_records(question)
    if rec:
        return rec.get("answer"), score
    pairs = parse_faq_qa_pairs(faq_text)
    if not pairs:
        return None, score

    q_tokens = _normalize_for_match(question)
    if not q_tokens:
        return None, 0.0

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
        pair_score = (len(overlap) / len(q_tokens) + len(overlap) / len(faq_tokens)) / 2.0
        # Also accept if FAQ Q tokens are almost fully present in the question.
        if len(overlap) == len(faq_tokens) and len(faq_tokens) >= 2:
            pair_score = max(pair_score, 0.99)
        if pair_score > best_score:
            best_score = pair_score
            best_answer = faq_a

    if best_answer is not None and best_score >= 0.6:
        logger.info("Direct FAQ Q/A match score=%.2f", best_score)
        return best_answer, round(best_score, 3)
    return None, round(max(score, best_score), 3)


def match_faq_qa(question: str, faq_text: str) -> str | None:
    """Return an FAQ A: value when the question clearly matches a Q: line."""
    answer, _score = score_faq_qa(question, faq_text)
    return answer


def _parse_llm_faq_payload(raw: str) -> tuple[str, float | None]:
    """Parse model JSON; fall back to plain text with unknown confidence."""
    text = (raw or "").strip()
    if not text:
        return "", None
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict) and data.get("answer") is not None:
                answer = str(data.get("answer") or "").strip()
                conf_raw = data.get("confidence")
                confidence = None
                if conf_raw is not None:
                    confidence = max(0.0, min(1.0, float(conf_raw)))
                return answer, confidence
    except Exception:
        logger.info("FAQ LLM response was not valid confidence JSON; using raw text")
    return text, None


def answer_faq_detailed(question: str, *, faq_path: Path | None = None) -> FaqAnswer:
    """Answer with keyword score and/or LLM-reported confidence."""
    started = time.perf_counter()
    faq_load_ms = 0.0
    retrieve_ms = 0.0
    openai_call_ms = 0.0
    retrieval_mode = "unknown"
    llm_invocations = 0
    result = FaqAnswer(answer=FAQ_NOT_FOUND_MESSAGE)

    try:
        cleaned_question = (question or "").strip()
        if not cleaned_question:
            result = FaqAnswer(
                answer=FAQ_NOT_FOUND_MESSAGE,
                confidence=0.0,
                match_score=0.0,
                retrieval_mode="empty",
            )
            return result

        faq_started = time.perf_counter()
        try:
            from app.faq_records import ensure_faq_records_seeded

            ensure_faq_records_seeded()
        except Exception:
            logger.exception("FAQ records seed check failed")
        faq_text = load_faq_text(faq_path=faq_path)
        faq_load_ms = (time.perf_counter() - faq_started) * 1000

        if faq_path is None:
            rec, match_score = score_faq_records(cleaned_question)
            if rec:
                retrieval_mode = "direct_qa"
                result = FaqAnswer(
                    answer=str(rec.get("answer") or ""),
                    confidence=match_score,
                    match_score=match_score,
                    retrieval_mode=retrieval_mode,
                    faq_id=rec.get("faq_id"),
                    source_name=rec.get("source") or None,
                    source_url=rec.get("source_url") or None,
                )
                return result
        else:
            direct, match_score = score_faq_qa(cleaned_question, faq_text)
            if direct:
                retrieval_mode = "direct_qa"
                result = FaqAnswer(
                    answer=direct,
                    confidence=match_score,
                    match_score=match_score,
                    retrieval_mode=retrieval_mode,
                )
                return result

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
        create_kwargs = {
            "model": OPENAI_MODEL,
            "instructions": SYSTEM_INSTRUCTIONS,
            "input": user_input,
            "temperature": FAQ_LLM_TEMPERATURE,
        }
        try:
            response = client.responses.create(**create_kwargs)
        except Exception as exc:
            # Some newer models (e.g. gpt-5-mini) reject temperature.
            if "temperature" in str(exc).lower():
                create_kwargs.pop("temperature", None)
                response = client.responses.create(**create_kwargs)
            else:
                raise
        openai_call_ms = (time.perf_counter() - openai_started) * 1000
        llm_invocations = 1

        raw = _extract_output_text(response)
        if not raw:
            raise RuntimeError("OpenAI returned an empty response")
        answer, confidence = _parse_llm_faq_payload(raw)
        if not answer:
            raise RuntimeError("OpenAI returned an empty answer field")
        # Never trust a model-invented Source; attach from FAQ Source column.
        answer = strip_source_lines(answer)
        source_name = None
        source_url = None
        faq_id = None
        if answer.strip() != FAQ_NOT_FOUND_MESSAGE:
            best_rec, _best_score = _best_faq_record(cleaned_question)
            if best_rec:
                faq_id = best_rec.get("faq_id")
                source_name = _clean_source(best_rec.get("source"))
                source_url = _clean_source(best_rec.get("source_url"))
            if not source_name:
                source_name, source_url = resolve_source(faq_text, excerpts)
        result = FaqAnswer(
            answer=answer,
            confidence=confidence,
            match_score=match_score,
            retrieval_mode=retrieval_mode,
            llm_invocations=llm_invocations,
            source_name=source_name,
            source_url=source_url,
            faq_id=faq_id,
        )
        return result
    except Exception:
        logger.exception("FAQ answer failed for question_len=%s", len(question or ""))
        result = FaqAnswer(
            answer=PARENT_FALLBACK_MESSAGE,
            confidence=0.0,
            retrieval_mode="error",
            llm_invocations=llm_invocations,
        )
        return result
    finally:
        total_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "faq_load_ms=%.1f retrieve_ms=%.1f openai_call_ms=%.1f "
            "total_faq_answer_ms=%.1f retrieval_mode=%s confidence=%s match_score=%s",
            faq_load_ms,
            retrieve_ms,
            openai_call_ms,
            total_ms,
            result.retrieval_mode,
            result.confidence,
            result.match_score,
        )


def answer_faq_question(question: str, *, faq_path: Path | None = None) -> str:
    """Answer a parent question using FAQ Q/A match first, then RAG + LLM."""
    return answer_faq_detailed(question, faq_path=faq_path).answer


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
