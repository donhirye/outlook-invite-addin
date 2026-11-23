"""Engine 1 — FAQ + calendar overview + existing non-guided routing."""

from __future__ import annotations

from app.calendar_service import answer_calendar_question, looks_like_calendar_question
from app.config import OPENAI_MODEL
from app.engines.base import ENGINE_1, AnswerResult, ConversationContext, ModelUsage
from app.engines.registry import register_engine
from app.faq_admin import HELP_TEXT, format_parent_answer, is_help_command
from app.faq_service import answer_faq_detailed
from app.overview_service import answer_overview, is_overview_question
from app.privacy_filter import privacy_reply_if_needed


class LegacyEngine:
    id = ENGINE_1
    version = "1.0.0"
    title = "Engine 1 — Legacy baseline"
    implemented = True

    def answer(self, ctx: ConversationContext) -> AnswerResult:
        text = (ctx.text or "").strip()

        if is_help_command(text):
            return AnswerResult(
                messages=[HELP_TEXT],
                route="help",
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

        # Date-list / "what's going on" — retrieve all in window; LLM reshape if filtered.
        if is_overview_question(text):
            overview = answer_overview(text)
            if overview:
                llm_n = int(overview.get("llm_invocations") or 0)
                return AnswerResult(
                    messages=overview["messages"],
                    route="overview",
                    engine_id=self.id,
                    engine_version=self.version,
                    intent="overview",
                    sources=list(overview.get("sources") or []),
                    answer_outcome=overview.get("answer_outcome") or "answered",
                    retrieval_mode=overview.get("retrieval_mode") or "overview",
                    retrieved_chunks=list(overview.get("retrieved_chunks") or []),
                    source_name=overview.get("source_name"),
                    source_url=overview.get("source_url"),
                    faq_id=overview.get("faq_id"),
                    fallback=overview.get("fallback"),
                    model_usage=ModelUsage(
                        model=overview.get("model") if llm_n else None,
                        invocations=llm_n,
                        input_tokens=overview.get("input_tokens")
                        if isinstance(overview.get("input_tokens"), int)
                        else None,
                        output_tokens=overview.get("output_tokens")
                        if isinstance(overview.get("output_tokens"), int)
                        else None,
                    ),
                )

        # School calendar (deterministic holiday / named-event) before FAQ/LLM.
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

        # FAQ path (direct records + sibling synth, then RAG + LLM).
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
