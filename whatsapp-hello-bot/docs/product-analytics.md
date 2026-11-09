# Product analytics

## Event source

Durable JSONL events in `data/analytics_events.jsonl` (optional GCS mirror). Written for every processed message after dedupe.

## Session definition

New session after **30 minutes** of inactivity per `user_hash`.

## Metrics

Engagement: DAU, WAU, unique users, messages, repeat users, sessions, messages/session.

Answering: FAQ/guided/human/clarification/unknown rates, latency avg/p50/p95, error rate.

Guided: started/completed/resolved/partial/unresolved (existing guided_metrics) + abandonment estimate (started − completed).

Outcomes:

- Reported self-service resolution rate = resolved / (resolved+partial+unresolved)
- Feedback response rate = feedback count / guided started
- Knowledge coverage = share of messages routed to faq/guided/human (not correctness)
- Estimated admin minutes saved = FAQ-route count × configurable minutes (default 3) — **estimate only**

## Admin UI

Analytics → Product tab. Filter by days and engine.
