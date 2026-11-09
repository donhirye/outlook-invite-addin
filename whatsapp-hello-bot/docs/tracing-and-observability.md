# Tracing and observability

## Goals

Understand how every message was processed without logging raw phones or full message bodies.

## Implementation

- Trace ID per message (`app/observability/tracing.py`)
- Pseudonymous `user_hash` via HMAC (`app/observability/privacy.py`)
- Spans: engine selected, answered/error
- Persisted JSONL: `data/answer_traces.jsonl` (+ optional GCS mirror)
- Structured Cloud Logging line includes `trace_id`, engine, route, latency

## Fields captured

trace_id, ts, user_hash, message fingerprint, engine id/version, route, faq/flow/step ids, intent, extracted keys (not values with PII), model/prompt version, LLM invocation count, tokens when available, latency, error/fallback, status.

## Admin

Analytics → Engine → Trace explorer (admin auth required).

## Not included

No custom distributed tracing backend. OpenTelemetry optional later. Cloud Logging remains the deep technical layer.
