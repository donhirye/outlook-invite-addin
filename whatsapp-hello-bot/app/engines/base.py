"""Shared answering-engine contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


ENGINE_1 = "engine1_legacy"
ENGINE_2 = "engine2_hybrid"
ENGINE_3 = "engine3_reserved"
ENGINE_4 = "engine4_reserved"

IMPLEMENTED_ENGINES = {ENGINE_1, ENGINE_2}


@dataclass
class ConversationContext:
    phone_hash: str
    phone: str
    message_id: str
    text: str
    message_type: str = "text"
    guided_session: dict[str, Any] | None = None
    pinned_engine_id: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelUsage:
    model: str | None = None
    prompt_version: str | None = None
    invocations: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None


@dataclass
class AnswerResult:
    messages: list[str]
    choices: list[dict[str, str]] | None = None
    route: str = "unknown"  # faq | guided_start | guided_continue | human | help | greeting | faq_admin | clarification | unknown
    engine_id: str = ENGINE_1
    engine_version: str = "1.0.0"
    faq_id: str | None = None
    faq_match_score: float | None = None
    answer_confidence: float | None = None
    retrieval_mode: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    flow_id: str | None = None
    step_id: str | None = None
    intent: str | None = None
    extracted: dict[str, Any] = field(default_factory=dict)
    state_transition: str | None = None
    model_usage: ModelUsage = field(default_factory=ModelUsage)
    fallback: str | None = None
    # answered | unanswered | error — no question/answer text stored with this.
    answer_outcome: str | None = None
    error: str | None = None
    sources: list[str] = field(default_factory=list)
    ended: bool = False
    skip_outbound: bool = False


class AnsweringEngine(Protocol):
    id: str
    version: str
    title: str
    implemented: bool

    def answer(self, ctx: ConversationContext) -> AnswerResult: ...
