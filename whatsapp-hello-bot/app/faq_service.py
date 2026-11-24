import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

from app.config import (
    FAQ_NOT_FOUND_MESSAGE,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_REASONING_EFFORT,
    PARENT_FALLBACK_MESSAGE,
)
from app.faq_rag import retrieve_chunks
from app.faq_records import chicago_today
from app.faq_store import get_faq_text

logger = logging.getLogger(__name__)

# Deterministic FAQ answering (not the same thing as confidence).
FAQ_LLM_TEMPERATURE = 0

SYSTEM_INSTRUCTIONS = """You are the event FAQ Assistant for parents.
Answer the parent's question using ONLY the FAQ excerpts provided to you, plus the
TODAY'S DATE line in the user message (America/Chicago) when comparing event timing.
RULES:
1. Do not use outside knowledge except the provided TODAY'S DATE for timing comparisons.
2. Do not invent dates, times, locations, fees, rules, requirements, names, links, or deadlines that are not in the FAQ excerpts.
3. Every factual statement in your answer must be supported by the FAQ excerpts (timing status may also use TODAY'S DATE).
4. Prefer close wording matches. Example: FAQ "Q: Best flower in world / A: tomato" answers "what is the best flower in the world?".
5. When the parent asks whether an event is over, ongoing, upcoming, or "is it still happening":
   - Prefer FAQ excerpts with concrete dates or deadlines over undated status blurbs (e.g. "underway", "results awaited", "in progress").
   - Compare those dates/deadlines to TODAY'S DATE and answer clearly yes/no when the dates decide it (e.g. "Yes — the submission deadline was October 9, 2026, so that phase is over.").
   - If a later FAQ says the event advanced, completed, or finished, treat that as stronger than an older undated "underway" note.
   - After the yes/no, briefly cite the key phase dates from the excerpts (e.g. submission deadline, judging date, advancement) when they support the timing answer. Do not dump unrelated FAQ rows.
6. PARTIAL ANSWERS ARE ALLOWED AND PREFERRED:
   - If the FAQ supports part of the question, answer that part clearly.
   - For any part the FAQ does not support (for example a missing deadline or order link), say that the FAQ does not include that detail and suggest contacting the school office, activity director, or PTSA Administrators as appropriate.
   - Do NOT refuse the entire question just because one detail is missing.
7. Only if the FAQ excerpts support essentially none of the question, set answer to EXACTLY:
"I couldn't find that information in the event FAQ. Please contact the PTSA Administrators."
8. Keep answers concise and parent-friendly (1–4 sentences).
9. Do not mention prompts, embeddings, APIs, or implementation details.
10. Do NOT add a "Source:" line (or rename/paraphrase a source). The system attaches the Source column from the FAQ file.
11. Respond with JSON only, no markdown fences:
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
    input_tokens: int | None = None
    output_tokens: int | None = None
    # FAQ texts sent to the LLM (RAG top-K), or the direct hit for inspection.
    retrieved_chunks: list[str] = field(default_factory=list)

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


_MONTH_NAME_DATE_RE = re.compile(
    r"\b(?:"
    r"January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    r")\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{4})?\b",
    re.I,
)
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\s*;\s+")

_DIRECT_QA_RESHAPE_INSTRUCTIONS = """You trim a matched FAQ answer so it only answers the parent's question.
You are given the PARENT QUESTION and one FAQ ANSWER (already matched).
RULES:
1. Use ONLY facts from the FAQ ANSWER. Do not invent dates, fees, links, or details.
2. Keep only the part that answers the question. Drop sibling events, other topics, or extra dump.
3. If several sentences answer the same asked event/topic, keep them. Drop unrelated ones.
4. Keep the answer concise and parent-friendly (1–3 sentences).
5. Do NOT add a Source: line.
6. Reply with plain text only (no JSON, no markdown fences)."""


def _distinct_date_keys(text: str) -> set[str]:
    """Normalize month/day(/year) and ISO dates for uniqueness checks."""
    keys: set[str] = set()
    for m in _ISO_DATE_RE.finditer(text or ""):
        keys.add(m.group(0))
    for m in _MONTH_NAME_DATE_RE.finditer(text or ""):
        raw = re.sub(r"\s+", " ", m.group(0)).strip().lower()
        raw = re.sub(r"(st|nd|rd|th)\b", "", raw)
        raw = raw.replace(",", "")
        keys.add(raw)
    return keys


def _split_answer_sentences(answer: str) -> list[str]:
    parts = [
        p.strip()
        for p in _SENTENCE_SPLIT_RE.split((answer or "").strip())
        if p and p.strip()
    ]
    return parts


def needs_direct_qa_reshape(question: str, answer: str) -> bool:
    """True when a pasted FAQ Q/A answer looks broader than the ask (dump risk).

    Cheap code gate — not an LLM. Triggers when the answer has multiple distinct
    dates, or later sentences look like sibling topics vs the question.
    """
    q = (question or "").strip()
    a = (answer or "").strip()
    if not q or not a:
        return False
    if len(_distinct_date_keys(a)) >= 2:
        return True
    sentences = _split_answer_sentences(a)
    if len(sentences) < 2:
        return False
    q_tokens = _normalize_for_match(q)
    if len(q_tokens) < 2:
        return False
    first_tokens = _normalize_for_match(sentences[0])
    if len(q_tokens & first_tokens) < 2:
        return False
    later_tokens = _normalize_for_match(" ".join(sentences[1:]))
    if not later_tokens:
        return False
    # Later sentences barely mention the ask → likely multi-topic dump.
    return len(q_tokens & later_tokens) <= 1


def reshape_direct_qa_with_llm(
    question: str,
    answer: str,
) -> tuple[str | None, dict]:
    """LLM trims a direct FAQ Q/A answer to the asked topic. Returns (text, usage)."""
    usage: dict = {
        "llm_invocations": 0,
        "input_tokens": None,
        "output_tokens": None,
    }
    if not OPENAI_API_KEY:
        return None, usage
    q = (question or "").strip()
    a = (answer or "").strip()
    if not q or not a:
        return None, usage
    user_input = f"PARENT QUESTION:\n{q}\n\nFAQ ANSWER:\n{a}"
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        create_kwargs: dict = {
            "model": OPENAI_MODEL,
            "instructions": _DIRECT_QA_RESHAPE_INSTRUCTIONS,
            "input": user_input,
        }
        if not str(OPENAI_MODEL).startswith("gpt-5"):
            create_kwargs["temperature"] = 0
        if OPENAI_REASONING_EFFORT:
            create_kwargs["reasoning"] = {"effort": OPENAI_REASONING_EFFORT}
        try:
            response = client.responses.create(**create_kwargs)
        except Exception as exc:
            msg = str(exc).lower()
            retried = False
            if "temperature" in msg and "temperature" in create_kwargs:
                create_kwargs.pop("temperature", None)
                retried = True
            if "reasoning" in msg and "reasoning" in create_kwargs:
                create_kwargs.pop("reasoning", None)
                retried = True
            if not retried:
                raise
            response = client.responses.create(**create_kwargs)
        usage["llm_invocations"] = 1
        u = getattr(response, "usage", None)
        usage["input_tokens"] = getattr(u, "input_tokens", None)
        usage["output_tokens"] = getattr(u, "output_tokens", None)
        text = (getattr(response, "output_text", None) or "").strip()
        if not text:
            for item in getattr(response, "output", None) or []:
                for part in getattr(item, "content", None) or []:
                    t = getattr(part, "text", None)
                    if t:
                        text = str(t).strip()
                        break
                if text:
                    break
        text = strip_source_lines(text)
        return (text or None), usage
    except Exception:
        logger.exception("Direct FAQ Q/A reshape failed")
        return None, usage


def _apply_direct_qa_reshape(
    question: str,
    answer: str,
    *,
    allow_rag: bool,
) -> tuple[str, str, int, int | None, int | None]:
    """Maybe trim a direct Q/A paste. Returns answer, mode, llm_n, in_tok, out_tok."""
    mode = "direct_qa"
    if not allow_rag or not needs_direct_qa_reshape(question, answer):
        return answer, mode, 0, None, None
    reshaped, usage = reshape_direct_qa_with_llm(question, answer)
    if not reshaped:
        return answer, mode, int(usage.get("llm_invocations") or 0), usage.get(
            "input_tokens"
        ), usage.get("output_tokens")
    return (
        reshaped,
        "direct_qa_reshaped",
        int(usage.get("llm_invocations") or 1),
        usage.get("input_tokens") if isinstance(usage.get("input_tokens"), int) else None,
        usage.get("output_tokens")
        if isinstance(usage.get("output_tokens"), int)
        else None,
    )


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


_ORDINAL_TOKEN_RE = re.compile(r"^\d+(st|nd|rd|th)$", re.I)
# "is the book fair over?" needs TODAY + LLM — not a raw FAQ paste.
_TIMING_STATUS_RE = re.compile(
    r"\b("
    r"over|ended|done|finished|closed|still\s+open|still\s+happen\w*|"
    r"ongoing|upcoming|has\s+it\s+(started|ended|begun)|"
    r"is\s+it\s+(over|done|open|closed|ended|happening|upcoming)|"
    r"did\s+it\s+(end|happen|start)|already\s+(over|ended|done|closed)"
    r")\b",
    re.I,
)


def is_timing_status_question(text: str) -> bool:
    """True when the parent asks whether an event is over / still on."""
    return bool(_TIMING_STATUS_RE.search(text or ""))


_TIMING_TOPIC_STOP = frozenset(
    {
        "over",
        "ended",
        "done",
        "finished",
        "closed",
        "open",
        "still",
        "happening",
        "ongoing",
        "upcoming",
        "started",
        "begun",
        "already",
        "yet",
        "past",
        "passed",
        "competition",
        "event",
        "program",
        "status",
    }
)
_UNDATED_STATUS_RE = re.compile(
    r"\b("
    r"underway|in\s+progress|awaited|awaiting|pending|still\s+being|"
    r"results?\s+are\s+awaited|screening\s+process"
    r")\b",
    re.I,
)
_ADVANCEMENT_RE = re.compile(
    r"\b("
    r"advance(?:d|s|ment)?|selected\s+to\s+advance|moved\s+on|"
    r"district\s+level|completed|finished|concluded"
    r")\b",
    re.I,
)


def _ordinal_tokens(tokens: set[str]) -> set[str]:
    return {t for t in tokens if _ORDINAL_TOKEN_RE.match(t)}


def _format_record_chunk(rec: dict) -> str:
    return (
        f"Category: {rec.get('category') or ''}\n"
        f"Q: {rec.get('question') or ''}\n"
        f"A: {rec.get('answer') or ''}"
    ).strip()


def _record_has_usable_date(rec: dict) -> bool:
    if str(rec.get("event_date") or "").strip():
        return True
    blob = f"{rec.get('question') or ''} {rec.get('answer') or ''}"
    return bool(_distinct_date_keys(blob))


def _chunk_looks_undated_status(chunk: str) -> bool:
    """True for dateless 'underway/awaited' blurbs that mislead timing asks."""
    text = (chunk or "").strip()
    if not text:
        return False
    if _distinct_date_keys(text):
        return False
    return bool(_UNDATED_STATUS_RE.search(text))


def _timing_topic_tokens(question: str) -> set[str]:
    tokens = _normalize_for_match(question)
    return {t for t in tokens if t not in _TIMING_TOPIC_STOP and t not in _STOPWORDS}


def find_timing_evidence_records(
    question: str,
    *,
    limit: int = 4,
) -> list[dict]:
    """Topic-related FAQ rows with dates — preferred evidence for timing asks."""
    from app.faq_records import list_records

    topic = _timing_topic_tokens(question)
    if len(topic) < 1:
        return []
    scored: list[tuple[float, dict]] = []
    for rec in list_records(include_inactive=False):
        if not _record_has_usable_date(rec):
            continue
        faq_tokens = _normalize_for_match(
            f"{rec.get('question') or ''} {rec.get('answer') or ''} "
            f"{rec.get('category') or ''}"
        )
        overlap = topic & faq_tokens
        if not overlap:
            continue
        score = len(overlap) / max(len(topic), 1)
        # Prefer rows whose question/category also mention the topic.
        q_overlap = topic & _normalize_for_match(
            f"{rec.get('question') or ''} {rec.get('category') or ''}"
        )
        if q_overlap:
            score += 0.25 * (len(q_overlap) / max(len(topic), 1))
        if score >= 0.34:
            scored.append((score, rec))
    scored.sort(
        key=lambda pair: (
            pair[0],
            1 if str(pair[1].get("event_date") or "").strip() else 0,
            str(pair[1].get("published_date") or ""),
        ),
        reverse=True,
    )
    return [rec for _, rec in scored[: max(1, limit)]]


def merge_timing_evidence_chunks(
    question: str,
    chunks: list[str],
    *,
    seed_chunk: str | None = None,
) -> tuple[list[str], dict | None]:
    """Prepend dated topic FAQs; demote undated status blurbs for timing asks.

    Returns (ordered_chunks, best_dated_record_or_none).
    """
    dated_recs = find_timing_evidence_records(question)
    dated_chunks = [_format_record_chunk(r) for r in dated_recs]
    best_dated = dated_recs[0] if dated_recs else None

    ordered: list[str] = []
    seen: set[str] = set()

    def _add(chunk: str) -> None:
        key = (chunk or "").strip()
        if not key or key in seen:
            return
        seen.add(key)
        ordered.append(key)

    for chunk in dated_chunks:
        _add(chunk)
    if seed_chunk and not _chunk_looks_undated_status(seed_chunk):
        _add(seed_chunk)

    undated_status: list[str] = []
    for chunk in chunks or []:
        if _chunk_looks_undated_status(chunk) and dated_chunks:
            undated_status.append(chunk)
            continue
        _add(chunk)
    # Keep undated status only at the end (and only if nothing dated was found,
    # we already skipped demotion above when dated_chunks is empty).
    if not dated_chunks:
        for chunk in undated_status:
            _add(chunk)
    elif seed_chunk and _chunk_looks_undated_status(seed_chunk):
        # Explicit seed that is undated status: keep last, never first.
        _add(seed_chunk)

    return ordered, best_dated


def _best_faq_record(question: str) -> tuple[dict | None, float]:
    """Best structured FAQ record and score (no direct-match threshold)."""
    from datetime import datetime

    from app.faq_records import list_records

    records = list_records(include_inactive=False)
    if not records:
        return None, 0.0
    q_tokens = _normalize_for_match(question)
    if not q_tokens:
        return None, 0.0
    q_ord = _ordinal_tokens(q_tokens)
    today = chicago_today()
    upcoming = _wants_upcoming(question)
    best_rec = None
    best_score = 0.0
    for rec in records:
        q_text = rec.get("question") or ""
        a_text = rec.get("answer") or ""
        faq_q_tokens = _normalize_for_match(q_text)
        faq_a_tokens = _normalize_for_match(a_text)
        faq_tokens = faq_q_tokens | faq_a_tokens
        if not faq_q_tokens and not faq_a_tokens:
            continue
        q_overlap = q_tokens & faq_q_tokens
        a_overlap = q_tokens & faq_a_tokens
        if not q_overlap and not a_overlap:
            continue
        # Prefer question match; allow answer coverage so "6th grade orchestra concert"
        # can hit a FAQ whose Q is "upcoming music events" but A names that concert.
        q_score = 0.0
        if faq_q_tokens and q_overlap:
            q_score = (
                len(q_overlap) / len(q_tokens) + len(q_overlap) / len(faq_q_tokens)
            ) / 2.0
            if len(q_overlap) == len(faq_q_tokens) and len(faq_q_tokens) >= 2:
                q_score = max(q_score, 0.99)
        # Single-token answer hits are too noisy ("park" → Commissioner's Park).
        a_score = (
            len(a_overlap) / len(q_tokens)
            if len(a_overlap) >= 2
            else 0.0
        )
        score = max(q_score, 0.85 * a_score if a_score else 0.0)
        if q_score and a_score:
            score = max(score, 0.55 * q_score + 0.45 * a_score)

        # "6th grade …" must not prefer a 7th/8th-grade FAQ that never mentions 6th.
        faq_ord = _ordinal_tokens(faq_tokens)
        if q_ord and faq_ord and not (q_ord & faq_ord):
            score *= 0.35
        elif q_ord and (q_ord & faq_ord):
            score = min(1.0, score + 0.12)

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


def answer_faq_detailed(
    question: str,
    *,
    faq_path: Path | None = None,
    allow_rag: bool = True,
) -> FaqAnswer:
    """Answer with keyword score and/or LLM-reported confidence.

    When allow_rag is False, stop after direct match (no embeddings/LLM).
    """
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
        match_score = 0.0
        status_seed_chunk: str | None = None
        status_seed_meta: dict | None = None
        timing_ask = is_timing_status_question(cleaned_question)

        if faq_path is None:
            rec, match_score = score_faq_records(cleaned_question)
            if rec:
                direct_chunk = _format_record_chunk(rec)
                # "Is it over?" needs TODAY + LLM — not a raw date paste.
                if timing_ask:
                    if not allow_rag:
                        result = FaqAnswer(
                            answer=FAQ_NOT_FOUND_MESSAGE,
                            confidence=0.0,
                            match_score=match_score,
                            retrieval_mode="direct_miss",
                            faq_id=rec.get("faq_id"),
                            source_name=rec.get("source") or None,
                            source_url=rec.get("source_url") or None,
                            retrieved_chunks=[direct_chunk],
                        )
                        return result
                    status_seed_chunk = direct_chunk
                    status_seed_meta = rec
                    # Fall through to RAG/LLM with this record seeded into excerpts.
                else:
                    raw_answer = str(rec.get("answer") or "")
                    answer, retrieval_mode, reshape_llms, in_tok, out_tok = (
                        _apply_direct_qa_reshape(
                            cleaned_question,
                            raw_answer,
                            allow_rag=allow_rag,
                        )
                    )
                    result = FaqAnswer(
                        answer=answer,
                        confidence=match_score,
                        match_score=match_score,
                        retrieval_mode=retrieval_mode,
                        llm_invocations=reshape_llms,
                        faq_id=rec.get("faq_id"),
                        source_name=rec.get("source") or None,
                        source_url=rec.get("source_url") or None,
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        retrieved_chunks=[direct_chunk],
                    )
                    return result
        else:
            direct, match_score = score_faq_qa(cleaned_question, faq_text)
            if direct:
                answer, retrieval_mode, reshape_llms, in_tok, out_tok = (
                    _apply_direct_qa_reshape(
                        cleaned_question,
                        direct,
                        allow_rag=allow_rag,
                    )
                )
                result = FaqAnswer(
                    answer=answer,
                    confidence=match_score,
                    match_score=match_score,
                    retrieval_mode=retrieval_mode,
                    llm_invocations=reshape_llms,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    retrieved_chunks=[f"Q: {cleaned_question}\nA: {direct}"],
                )
                return result

        if not allow_rag:
            result = FaqAnswer(
                answer=FAQ_NOT_FOUND_MESSAGE,
                confidence=0.0,
                match_score=match_score,
                retrieval_mode="direct_miss",
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
        if timing_ask and faq_path is None:
            # Prefer dated topic FAQs; demote undated "underway/awaited" blurbs.
            chunks, best_dated = merge_timing_evidence_chunks(
                cleaned_question,
                chunks,
                seed_chunk=status_seed_chunk,
            )
            if best_dated:
                status_seed_meta = best_dated
                if not match_score:
                    match_score = 0.0
        elif status_seed_chunk:
            # Ensure the direct-matched event FAQ is in the LLM excerpts.
            if status_seed_chunk not in chunks:
                chunks = [status_seed_chunk, *chunks]
        retrieve_ms = (time.perf_counter() - retrieve_started) * 1000
        retrieval_mode = (
            "full_faq"
            if len(chunks) == 1 and chunks[0].strip() == faq_text.strip()
            else "rag"
        )
        excerpts = "\n\n---\n\n".join(chunks)

        today = chicago_today()
        user_input = (
            f"TODAY'S DATE (America/Chicago): {today.isoformat()} "
            f"({today.strftime('%A, %B %d, %Y')})\n\n"
            f"FAQ EXCERPTS:\n{excerpts}\n\n"
            f"PARENT QUESTION:\n{cleaned_question}"
        )

        client = OpenAI(api_key=OPENAI_API_KEY)
        openai_started = time.perf_counter()
        create_kwargs: dict = {
            "model": OPENAI_MODEL,
            "instructions": SYSTEM_INSTRUCTIONS,
            "input": user_input,
        }
        # gpt-5* rejects temperature; older chat models accept it.
        if not str(OPENAI_MODEL).startswith("gpt-5"):
            create_kwargs["temperature"] = FAQ_LLM_TEMPERATURE
        if OPENAI_REASONING_EFFORT:
            create_kwargs["reasoning"] = {"effort": OPENAI_REASONING_EFFORT}
        try:
            response = client.responses.create(**create_kwargs)
        except Exception as exc:
            msg = str(exc).lower()
            # Strip unsupported params and retry (once per param).
            retried = False
            if "temperature" in msg and "temperature" in create_kwargs:
                create_kwargs.pop("temperature", None)
                retried = True
            if "reasoning" in msg and "reasoning" in create_kwargs:
                create_kwargs.pop("reasoning", None)
                retried = True
            if retried:
                response = client.responses.create(**create_kwargs)
            else:
                raise
        openai_call_ms = (time.perf_counter() - openai_started) * 1000
        llm_invocations = 1
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)

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
            seed = status_seed_meta
            if seed:
                faq_id = seed.get("faq_id")
                source_name = _clean_source(seed.get("source"))
                source_url = _clean_source(seed.get("source_url"))
            if not faq_id:
                best_rec, _best_score = _best_faq_record(cleaned_question)
                if best_rec:
                    faq_id = best_rec.get("faq_id")
                    source_name = source_name or _clean_source(best_rec.get("source"))
                    source_url = source_url or _clean_source(best_rec.get("source_url"))
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
            input_tokens=input_tokens if isinstance(input_tokens, int) else None,
            output_tokens=output_tokens if isinstance(output_tokens, int) else None,
            retrieved_chunks=list(chunks),
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
