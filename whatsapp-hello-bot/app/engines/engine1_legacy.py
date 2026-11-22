"""Engine 1 — FAQ + calendar + existing non-guided routing."""

from __future__ import annotations

from app.calendar_picker import (
    is_show_calendar_question,
    resolve_calendar_pick,
    start_calendar_picker,
)
from app.calendar_service import answer_calendar_question, looks_like_calendar_question
from app.config import OPENAI_MODEL
from app.engines.base import ENGINE_1, AnswerResult, ConversationContext, ModelUsage
from app.engines.registry import register_engine
from app.faq_admin import (
    FAQ_USAGE_TEXT,
    HELP_TEXT,
    append_faq_entry,
    format_parent_answer,
    is_faq_admin,
    is_faq_command,
    is_help_command,
    is_opener_message,
    parse_faq_command,
)
from app.faq_service import answer_faq_detailed
from app.greeting_store import get_greeting
from app.privacy_filter import privacy_reply_if_needed


class LegacyEngine:
    id = ENGINE_1
    version = "1.0.0"
    title = "Engine 1 — Legacy baseline"
    implemented = True

    def answer(self, ctx: ConversationContext) -> AnswerResult:
        text = (ctx.text or "").strip()
        phone = ctx.phone

        if is_help_command(text):
            return AnswerResult(
                messages=[HELP_TEXT],
                route="help",
                engine_id=self.id,
                engine_version=self.version,
            )

        if ctx.message_type == "text" and is_opener_message(text):
            return AnswerResult(
                messages=[get_greeting()],
                route="greeting",
                engine_id=self.id,
                engine_version=self.version,
            )

        if is_faq_command(text):
            if not is_faq_admin(phone):
                return AnswerResult(
                    messages=["Only event admins can use /faq."],
                    route="faq_admin",
                    engine_id=self.id,
                    engine_version=self.version,
                )
            parsed = parse_faq_command(text)
            if not parsed:
                return AnswerResult(
                    messages=[FAQ_USAGE_TEXT],
                    route="faq_admin",
                    engine_id=self.id,
                    engine_version=self.version,
                )
            q_text, a_text, source = parsed
            confirmation = append_faq_entry(q_text, a_text, source)
            return AnswerResult(
                messages=[confirmation],
                route="faq_admin",
                engine_id=self.id,
                engine_version=self.version,
            )

        # PTSA privacy: block asks for student name / ID / phone / email.
        privacy = privacy_reply_if_needed(text)
        if privacy:
            return AnswerResult(
                messages=[privacy],
                route="privacy_filter",
                engine_id=self.id,
                engine_version=self.version,
                intent="privacy",
                answer_outcome="answered",
                sources=["ptsa_privacy_policy"],
            )

        # "Show me the calendar": ask which calendar, then list its upcoming events.
        picked = resolve_calendar_pick(phone, text)
        if picked:
            return AnswerResult(
                messages=picked["messages"],
                route="calendar",
                engine_id=self.id,
                engine_version=self.version,
                intent="calendar",
                sources=["school_calendar"],
                answer_outcome="answered",
                retrieval_mode="calendar",
            )
        if is_show_calendar_question(text):
            asked = start_calendar_picker(phone)
            if asked:
                return AnswerResult(
                    messages=asked["messages"],
                    choices=asked["choices"],
                    route="calendar",
                    engine_id=self.id,
                    engine_version=self.version,
                    intent="calendar",
                    sources=["school_calendar"],
                    answer_outcome="answered",
                    retrieval_mode="calendar",
                )

        # School calendar (deterministic) before FAQ/LLM.
        if looks_like_calendar_question(text):
            cal = answer_calendar_question(text)
            if cal.get("handled") and cal.get("answer"):
                return AnswerResult(
                    messages=[cal["answer"]],
                    route="calendar",
                    engine_id=self.id,
                    engine_version=self.version,
                    intent="calendar",
                    sources=["school_calendar"],
                    answer_outcome="answered",
                    source_name=cal.get("source_name"),
                    source_url=cal.get("source_url"),
                    retrieval_mode="calendar",
                )

        # FAQ path (direct records, then RAG + LLM).
        faq = answer_faq_detailed(text)
        raw = faq.answer
        answer = format_parent_answer(
            raw,
            source_name=faq.source_name,
            source_url=faq.source_url,
        )
        lowered = (raw or "").strip().lower()
        if not raw or lowered.startswith("sorry,"):
            fallback = "faq_fallback"
            outcome = "unanswered"
        elif "couldn't find that information" in lowered:
            fallback = "faq_not_found"
            outcome = "unanswered"
        else:
            fallback = None
            outcome = "answered"
        return AnswerResult(
            messages=[answer],
            route="faq",
            engine_id=self.id,
            engine_version=self.version,
            intent="faq",
            sources=["faq_records"],
            model_usage=ModelUsage(
                model=OPENAI_MODEL if faq.llm_invocations else None,
                invocations=faq.llm_invocations,
                input_tokens=getattr(faq, "input_tokens", None),
                output_tokens=getattr(faq, "output_tokens", None),
            ),
            fallback=fallback,
            answer_outcome=outcome,
            faq_id=faq.faq_id,
            faq_match_score=faq.match_score,
            answer_confidence=faq.confidence,
            retrieval_mode=faq.retrieval_mode,
            retrieved_chunks=list(getattr(faq, "retrieved_chunks", None) or []),
            source_name=faq.source_name,
            source_url=faq.source_url,
        )


register_engine(LegacyEngine())
