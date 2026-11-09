"""Shared product analytics derived from durable events + guided metrics."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from app.guided_metrics import get_guided_metrics
from app.observability.analytics_store import (
    ABANDON_IDLE_MINUTES,
    load_events,
    sessionize,
)
from app.observability.tracing import load_traces

# Configurable estimate assumptions (minutes).
DEFAULT_MINUTES_PER_REPETITIVE_QUESTION = 3.0


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def compute_product_analytics(
    *,
    since_days: int = 30,
    engine_id: str | None = None,
    minutes_per_question: float = DEFAULT_MINUTES_PER_REPETITIVE_QUESTION,
) -> dict[str, Any]:
    raw = load_events(since_days=since_days)
    if engine_id and engine_id != "all":
        raw = [e for e in raw if e.get("engine_id") == engine_id]
    events = sessionize([e for e in raw if e.get("type") == "message_processed"])

    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    users = {e.get("user_hash") for e in events if e.get("user_hash")}
    dau = {
        e.get("user_hash")
        for e in events
        if (_parse_ts(e.get("ts")) or now) >= day_ago and e.get("user_hash")
    }
    wau = {
        e.get("user_hash")
        for e in events
        if (_parse_ts(e.get("ts")) or now) >= week_ago and e.get("user_hash")
    }

    by_user = Counter(e.get("user_hash") for e in events if e.get("user_hash"))
    repeat_users = sum(1 for _, n in by_user.items() if n >= 2)
    sessions = {e.get("session_id") for e in events if e.get("session_id")}
    msgs_per_session = (
        round(len(events) / len(sessions), 2) if sessions else 0.0
    )

    routes = Counter(e.get("route") for e in events)
    total = len(events) or 1
    latencies = [float(e.get("latency_ms") or 0) for e in events if e.get("latency_ms") is not None]
    latencies_sorted = sorted(latencies)
    p95 = (
        latencies_sorted[int(0.95 * (len(latencies_sorted) - 1))]
        if latencies_sorted
        else None
    )

    guided = get_guided_metrics()
    completed = int(guided.get("guided_completed") or 0)
    resolved = int(guided.get("resolved") or 0)
    feedback_total = (
        int(guided.get("resolved") or 0)
        + int(guided.get("partial") or 0)
        + int(guided.get("unresolved") or 0)
    )
    started = int(guided.get("guided_started") or 0)
    abandoned_est = max(0, started - completed)

    faq_like = routes.get("faq", 0)
    guided_like = routes.get("guided_start", 0) + routes.get("guided_continue", 0)
    coverage = round(faq_like / total, 3) if events else 0.0
    # Knowledge coverage: messages that got faq or guided (not unknown/human-only invent)
    answered = faq_like + guided_like + routes.get("human", 0)
    knowledge_coverage = round(answered / total, 3) if events else 0.0

    outcomes = Counter(str(e.get("answer_outcome") or "unknown") for e in events)
    unanswered_count = int(outcomes.get("unanswered", 0))
    answered_count = int(outcomes.get("answered", 0))
    outcome_known = unanswered_count + answered_count + int(outcomes.get("error", 0))

    admin_minutes = round(faq_like * minutes_per_question, 1)

    return {
        "since_days": since_days,
        "engine_filter": engine_id or "all",
        "dau": len(dau),
        "wau": len(wau),
        "unique_users": len(users),
        "total_messages": len(events),
        "repeat_users": repeat_users,
        "sessions": len(sessions),
        "messages_per_session": msgs_per_session,
        "direct_faq_rate": round(routes.get("faq", 0) / total, 3),
        "guided_rate": round(guided_like / total, 3),
        "human_escalation_rate": round(routes.get("human", 0) / total, 3),
        "clarification_rate": round(routes.get("clarification", 0) / total, 3),
        "unknown_rate": round(routes.get("unknown", 0) / total, 3),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "p50_latency_ms": round(median(latencies), 1) if latencies else None,
        "p95_latency_ms": round(p95, 1) if p95 is not None else None,
        "error_rate": round(
            sum(1 for e in events if e.get("status") == "error") / total, 3
        ),
        "routing_distribution": dict(routes),
        "guided": guided,
        "guided_completion_rate": round(completed / started, 3) if started else 0.0,
        "reported_resolution_rate": round(resolved / feedback_total, 3)
        if feedback_total
        else 0.0,
        "feedback_response_rate": round(feedback_total / started, 3) if started else 0.0,
        "guided_abandonment_estimate": abandoned_est,
        "abandonment_definition": (
            f"started - completed (idle threshold documented as "
            f"{ABANDON_IDLE_MINUTES} minutes; exact step drop-off requires richer step events)"
        ),
        "knowledge_coverage": knowledge_coverage,
        "knowledge_coverage_definition": (
            "Share of processed messages routed to faq, guided, or human handoff "
            "(not a correctness score)."
        ),
        "answered_count": answered_count,
        "unanswered_count": unanswered_count,
        "unanswered_rate": round(unanswered_count / outcome_known, 3)
        if outcome_known
        else 0.0,
        "answer_outcome_distribution": dict(outcomes),
        "unanswered_definition": (
            "Messages classified unanswered (FAQ not found / FAQ error). "
            "Question and answer text are stored on each turn for later evals."
        ),
        "qa_log": _qa_log(since_days=since_days, limit=50),
        "estimated_admin_minutes_saved": admin_minutes,
        "admin_time_assumption_minutes": minutes_per_question,
        "admin_time_note": "Estimate only: FAQ-route count × configurable minutes.",
        "session_definition": "New session after 30 minutes of inactivity per user_hash.",
        "empty": len(events) == 0,
    }


def _qa_log(*, since_days: int = 30, limit: int = 50) -> list[dict[str, Any]]:
    """Recent question/answer pairs for admin review and eval harvesting."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, since_days))
    rows: list[dict[str, Any]] = []
    for t in load_traces(limit=max(limit * 4, 100)):
        ts = _parse_ts(t.get("ts"))
        if ts is not None and ts < cutoff:
            continue
        question = (t.get("question_text") or "").strip()
        answer = (t.get("answer_text") or "").strip()
        if not question and not answer:
            continue
        rows.append(
            {
                "ts": t.get("ts"),
                "trace_id": t.get("trace_id"),
                "engine_id": t.get("engine_id"),
                "route": t.get("route"),
                "answer_outcome": t.get("answer_outcome") or "unknown",
                "faq_match_score": t.get("faq_match_score"),
                "answer_confidence": t.get("answer_confidence"),
                "retrieval_mode": t.get("retrieval_mode") or "",
                "question_text": question,
                "answer_text": answer,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def compute_engine_analytics(*, since_days: int = 30) -> dict[str, Any]:
    events = [
        e
        for e in load_events(since_days=since_days)
        if e.get("type") == "message_processed"
    ]
    by_engine: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        by_engine[str(e.get("engine_id") or "unknown")].append(e)

    summary = {}
    for eid, rows in by_engine.items():
        routes = Counter(r.get("route") for r in rows)
        lats = [float(r.get("latency_ms") or 0) for r in rows]
        llm = sum(int(r.get("llm_invocations") or 0) for r in rows)
        summary[eid] = {
            "messages": len(rows),
            "routes": dict(routes),
            "avg_latency_ms": round(sum(lats) / len(lats), 1) if lats else None,
            "llm_invocations_total": llm,
            "llm_per_message": round(llm / len(rows), 3) if rows else 0.0,
            "error_rate": round(
                sum(1 for r in rows if r.get("status") == "error") / len(rows), 3
            )
            if rows
            else 0.0,
        }
    return {"since_days": since_days, "by_engine": summary, "empty": not events}
