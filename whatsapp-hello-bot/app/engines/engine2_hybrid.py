"""Engine 2 — context-aware hybrid (deterministic flows + selective NLP)."""

from __future__ import annotations

import re
from typing import Any

from app.config import GUIDED_ENABLED, OPENAI_API_KEY, OPENAI_MODEL
from app.engines.base import ENGINE_2, AnswerResult, ConversationContext, ModelUsage
from app.engines.engine1_legacy import LegacyEngine
from app.engines.registry import register_engine
from app.guided_engine import advance as advance_guided
from app.guided_engine import start_topic
from app.guided_router import match_guided_topic, needs_human, route_message
from app.guided_state import clear_session, get_session, set_session
from app.guided_store import get_topic

PROMPT_VERSION = "engine2-hybrid-v1"


def _extract_lost_found_context(text: str) -> dict[str, Any]:
    cleaned = (text or "").lower()
    out: dict[str, Any] = {}
    if re.search(r"\b(bus)\b", cleaned) and re.search(
        r"\b(left|lost|forgot|on the bus)\b", cleaned
    ):
        out["item_branch"] = "bus"
    elif re.search(r"\b(chromebook|laptop)\b", cleaned):
        out["item_branch"] = "chromebook"
    elif re.search(r"\b(student )?id\b|\bid card\b", cleaned):
        out["item_branch"] = "student_id"
    elif re.search(
        r"\b(pe shirt|jacket|case-?it|water bottle|clothing|shirt|coat|hoodie)\b",
        cleaned,
    ):
        out["item_branch"] = "clothing"

    if re.search(
        r"\b(already checked|checked both|both places|both locations|"
        r"checked (the )?lost ?& ?found|couldn't find it after checking)\b",
        cleaned,
    ):
        out["checked_lost_found"] = True
    if re.search(r"\b(not yet|haven't checked|has not checked)\b", cleaned):
        out["checked_lost_found"] = False

    if re.search(r"\b(actually|i meant|correction|instead)\b", cleaned):
        out["is_correction"] = True
    return out


def _maybe_llm_extract(text: str) -> tuple[dict[str, Any], ModelUsage]:
    """Optional structured extraction when heuristics are weak."""
    usage = ModelUsage(model=OPENAI_MODEL, prompt_version=PROMPT_VERSION, invocations=0)
    heuristic = _extract_lost_found_context(text)
    if heuristic.get("item_branch") or heuristic.get("checked_lost_found") is not None:
        return heuristic, usage
    if not OPENAI_API_KEY or len((text or "").split()) < 8:
        return heuristic, usage
    # Keep selective: only ask model for ambiguous longer utterances.
    try:
        from openai import OpenAI
        import json

        client = OpenAI(api_key=OPENAI_API_KEY)
        usage.invocations = 1
        resp = client.responses.create(
            model=OPENAI_MODEL,
            instructions=(
                "Extract structured facts for a school Lost & Found assistant. "
                "Return JSON only with keys: item_branch "
                "(clothing|student_id|chromebook|bus|null), "
                "checked_lost_found (true|false|null), is_correction (bool). "
                "Do not invent school policy."
            ),
            input=text,
        )
        raw = (getattr(resp, "output_text", None) or "").strip()
        # token fields vary by SDK version
        usage.input_tokens = getattr(getattr(resp, "usage", None), "input_tokens", None)
        usage.output_tokens = getattr(getattr(resp, "usage", None), "output_tokens", None)
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(raw[start : end + 1])
            if isinstance(data, dict):
                merged = {**heuristic, **{k: v for k, v in data.items() if v is not None}}
                return merged, usage
    except Exception:
        return heuristic, usage
    return heuristic, usage


def _jump_lost_found(phone: str, extracted: dict[str, Any]) -> AnswerResult | None:
    topic = get_topic("lost_and_found")
    if not topic:
        return None
    branch = extracted.get("item_branch")
    checked = extracted.get("checked_lost_found")

    # Start topic then fast-forward deterministically.
    start_topic(phone, "lost_and_found")
    session = get_session(phone) or {}

    if branch == "bus":
        result = advance_guided(phone, "Left on the bus")
    elif branch == "chromebook":
        result = advance_guided(phone, "Chromebook")
    elif branch == "student_id":
        result = advance_guided(phone, "Student ID")
    elif branch == "clothing":
        # Skip identify_item by choosing clothing, then maybe skip check question.
        result = advance_guided(phone, "Clothing / supplies")
        if checked is True:
            result = advance_guided(phone, "Checked, not found")
        elif checked is False:
            result = advance_guided(phone, "Not yet")
        else:
            # Leave parent on the "have you checked" step.
            pass
    else:
        return None

    return AnswerResult(
        messages=list(result.get("messages") or []),
        choices=result.get("choices"),
        route="guided_start",
        engine_id=ENGINE_2,
        engine_version="2.0.0",
        flow_id="lost_and_found",
        step_id=result.get("step_id"),
        intent="guided",
        extracted=extracted,
        state_transition="start_with_skip",
        ended=bool(result.get("ended")),
        sources=["guided:lost_and_found"],
    )


class HybridEngine:
    id = ENGINE_2
    version = "2.0.0"
    title = "Engine 2 — Context-aware hybrid"
    implemented = True

    def __init__(self) -> None:
        self._legacy = LegacyEngine()

    def answer(self, ctx: ConversationContext) -> AnswerResult:
        text = (ctx.text or "").strip()
        phone = ctx.phone
        session = get_session(phone)

        # Active session: handle corrections / topic change before rigid choice match.
        if GUIDED_ENABLED and session:
            extracted, usage = _maybe_llm_extract(text)
            topic_id = session.get("topic_id")

            # Explicit cancel/restart still via legacy engine path.
            if text.lower() in {"cancel", "stop", "quit", "restart", "menu"}:
                result = self._legacy.answer(ctx)
                result.engine_id = self.id
                result.engine_version = self.version
                return result

            # Correction while in lost & found → jump branch.
            if topic_id == "lost_and_found" and (
                extracted.get("is_correction") or extracted.get("item_branch")
            ):
                if extracted.get("item_branch"):
                    clear_session(phone)
                    jumped = _jump_lost_found(phone, extracted)
                    if jumped:
                        jumped.model_usage = usage
                        jumped.route = "guided_continue"
                        jumped.state_transition = "correction_reroute"
                        return jumped

            # Topic switch: new guided topic keywords while mid-flow.
            other = match_guided_topic(text)
            if other and other["id"] != topic_id and len(text.split()) >= 4:
                clear_session(phone)
                ctx2 = ConversationContext(
                    phone_hash=ctx.phone_hash,
                    phone=phone,
                    message_id=ctx.message_id,
                    text=text,
                    message_type=ctx.message_type,
                )
                return self.answer(ctx2)

            result = self._legacy.answer(ctx)
            result.engine_id = self.id
            result.engine_version = self.version
            result.extracted = extracted
            result.model_usage = usage
            return result

        # No session: human / FAQ / guided with skip support.
        if needs_human(text):
            result = self._legacy.answer(ctx)
            result.engine_id = self.id
            result.engine_version = self.version
            return result

        decision = route_message(phone, text) if GUIDED_ENABLED else {"kind": "faq"}
        if decision.get("kind") == "start_guided" and decision.get("topic_id") == "lost_and_found":
            extracted, usage = _maybe_llm_extract(text)
            jumped = _jump_lost_found(phone, extracted)
            if jumped and extracted.get("item_branch"):
                jumped.model_usage = usage
                return jumped

        result = self._legacy.answer(ctx)
        result.engine_id = self.id
        result.engine_version = self.version
        return result


register_engine(HybridEngine())
