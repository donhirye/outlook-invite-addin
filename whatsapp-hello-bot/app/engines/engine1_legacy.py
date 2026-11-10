"""Engine 1 — legacy baseline (FAQ + guided + existing routing)."""

from __future__ import annotations

from app.calendar_service import answer_calendar_question, looks_like_calendar_question
from app.config import GUIDED_ENABLED, OPENAI_MODEL
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
from app.guided_engine import advance as advance_guided
from app.guided_router import begin_guided, route_message
from app.guided_state import get_session


class LegacyEngine:
    id = ENGINE_1
    version = "1.0.0"
    title = "Engine 1 — Legacy baseline"
    implemented = True

    def answer(self, ctx: ConversationContext) -> AnswerResult:
        text = (ctx.text or "").strip()
        phone = ctx.phone

        if is_help_command(text) and not get_session(phone):
            return AnswerResult(
                messages=[HELP_TEXT],
                route="help",
                engine_id=self.id,
                engine_version=self.version,
            )

        if (
            ctx.message_type == "text"
            and is_opener_message(text)
            and not get_session(phone)
        ):
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
            q_text, a_text = parsed
            confirmation = append_faq_entry(q_text, a_text)
            return AnswerResult(
                messages=[confirmation],
                route="faq_admin",
                engine_id=self.id,
                engine_version=self.version,
            )

        if GUIDED_ENABLED and get_session(phone):
            result = advance_guided(phone, text)
            return AnswerResult(
                messages=list(result.get("messages") or []),
                choices=result.get("choices"),
                route="guided_continue",
                engine_id=self.id,
                engine_version=self.version,
                flow_id=(result.get("topic_id") or (get_session(phone) or {}).get("topic_id")),
                step_id=result.get("step_id") or (get_session(phone) or {}).get("step_id"),
                state_transition="continue",
                ended=bool(result.get("ended")),
            )

        if GUIDED_ENABLED:
            decision = route_message(phone, text)
            kind = decision.get("kind")
            if kind == "start_guided":
                result = begin_guided(phone, decision["topic_id"])
                return AnswerResult(
                    messages=list(result.get("messages") or []),
                    choices=result.get("choices"),
                    route="guided_start",
                    engine_id=self.id,
                    engine_version=self.version,
                    flow_id=decision["topic_id"],
                    step_id=result.get("step_id"),
                    intent="guided",
                    state_transition="start",
                    ended=bool(result.get("ended")),
                )
            if kind == "human":
                return AnswerResult(
                    messages=[
                        decision.get("reply")
                        or "Please contact the school office for help with that."
                    ],
                    route="human",
                    engine_id=self.id,
                    engine_version=self.version,
                    intent="human",
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

        # Mode A FAQ path (may use LLM fallback inside faq_service).
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
            ),
            fallback=fallback,
            answer_outcome=outcome,
            faq_id=faq.faq_id,
            faq_match_score=faq.match_score,
            answer_confidence=faq.confidence,
            retrieval_mode=faq.retrieval_mode,
            source_name=faq.source_name,
            source_url=faq.source_url,
        )


register_engine(LegacyEngine())
