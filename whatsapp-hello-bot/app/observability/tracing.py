"""Lightweight structured traces for answering-engine processing."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from app.config import BASE_DIR, FAQ_GCS_BUCKET
from app.engines.base import AnswerResult
from app.observability.analytics_store import append_event
from app.observability.privacy import message_fingerprint, phone_hash

logger = logging.getLogger(__name__)

TRACES_FILE = BASE_DIR / "data" / "answer_traces.jsonl"
TRACES_GCS_OBJECT = "answer_traces.jsonl"
_lock = Lock()


@dataclass
class TraceSpan:
    name: str
    detail: dict[str, Any] = field(default_factory=dict)
    started_ms: float = 0.0
    duration_ms: float | None = None


@dataclass
class TraceContext:
    trace_id: str
    user_hash: str
    message_fp: str
    engine_id: str
    spans: list[TraceSpan] = field(default_factory=list)
    started: float = field(default_factory=time.perf_counter)

    def span(self, name: str, **detail: Any) -> TraceSpan:
        sp = TraceSpan(name=name, detail=detail, started_ms=(time.perf_counter() - self.started) * 1000)
        self.spans.append(sp)
        return sp


def new_trace(phone: str, message_id: str, engine_id: str) -> TraceContext:
    return TraceContext(
        trace_id=str(uuid.uuid4()),
        user_hash=phone_hash(phone),
        message_fp=message_fingerprint(message_id),
        engine_id=engine_id,
    )


def _persist_trace(record: dict[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False)
    with _lock:
        TRACES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with TRACES_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        if FAQ_GCS_BUCKET:
            try:
                from google.cloud import storage

                blob = storage.Client().bucket(FAQ_GCS_BUCKET).blob(TRACES_GCS_OBJECT)
                existing = blob.download_as_text(encoding="utf-8") if blob.exists() else ""
                blob.upload_from_string(
                    existing + line + "\n",
                    content_type="application/x-ndjson",
                )
            except Exception:
                logger.exception("Failed mirroring trace to GCS")


def finalize_trace(trace: TraceContext, result: AnswerResult, *, latency_ms: float) -> dict[str, Any]:
    record = {
        "trace_id": trace.trace_id,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_hash": trace.user_hash,
        "message_fp": trace.message_fp,
        "engine_id": result.engine_id,
        "engine_version": result.engine_version,
        "route": result.route,
        "faq_id": result.faq_id,
        "faq_match_score": result.faq_match_score,
        "intent": result.intent,
        "extracted_keys": sorted((result.extracted or {}).keys()),
        "flow_id": result.flow_id,
        "step_id": result.step_id,
        "state_transition": result.state_transition,
        "model": result.model_usage.model,
        "prompt_version": result.model_usage.prompt_version,
        "llm_invocations": result.model_usage.invocations,
        "input_tokens": result.model_usage.input_tokens,
        "output_tokens": result.model_usage.output_tokens,
        "estimated_cost_usd": result.model_usage.estimated_cost_usd,
        "latency_ms": round(latency_ms, 1),
        "error": result.error,
        "fallback": result.fallback,
        "status": "error" if result.error else "ok",
        "spans": [asdict(s) for s in trace.spans],
        # Never include raw message body or phone.
    }
    _persist_trace(record)
    append_event(
        {
            "type": "message_processed",
            "trace_id": trace.trace_id,
            "user_hash": trace.user_hash,
            "engine_id": result.engine_id,
            "route": result.route,
            "flow_id": result.flow_id,
            "step_id": result.step_id,
            "llm_invocations": result.model_usage.invocations,
            "latency_ms": round(latency_ms, 1),
            "status": record["status"],
            "fallback": result.fallback,
        }
    )
    logger.info(
        "trace_id=%s engine=%s route=%s flow=%s latency_ms=%.1f llm=%s status=%s",
        trace.trace_id,
        result.engine_id,
        result.route,
        result.flow_id,
        latency_ms,
        result.model_usage.invocations,
        record["status"],
    )
    return record


def load_traces(*, limit: int = 100) -> list[dict[str, Any]]:
    path = TRACES_FILE
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    out.reverse()
    return out


def get_trace(trace_id: str) -> dict[str, Any] | None:
    for row in load_traces(limit=2000):
        if row.get("trace_id") == trace_id:
            return row
    return None
