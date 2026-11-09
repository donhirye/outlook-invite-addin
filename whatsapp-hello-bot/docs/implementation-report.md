# Implementation report — Multi-engine platform

## 1. Architecture before / after

**Before:** Single webhook path with inline FAQ + guided routing.

**After:** Shared pipeline (`process_message`) + interchangeable engines (1 legacy, 2 hybrid, 3/4 reserved), structured traces, durable analytics events, eval harness, Admin Analytics (Product / Engine / Evaluations).

## 2. Files changed (high level)

- `app/engines/*` — contract, registry, engine1, engine2, stubs, pipeline
- `app/engine_config.py`, `app/observability/*`
- `app/main.py` — webhook via pipeline; Analytics routes
- `app/templates/admin_analytics*.html` + nav links
- `evals/*` — 77-case dataset + runner + reports
- `docs/*` — architecture, tracing, analytics, eval, comparison, deployment
- `.github/workflows/eval-engines.yml`

## 3. Persistence

Local JSON/JSONL (+ optional GCS when `FAQ_GCS_BUCKET` set):

- `engine_config.json`
- `analytics_events.jsonl`
- `answer_traces.jsonl`
- existing guided/FAQ stores unchanged

## 4–7. Evaluation (actual)

Dataset v1, 77 cases, mode `deterministic_mocked_safe`:

| Engine | Pass rate | Passed/Failed | Avg latency |
|--------|-----------|---------------|-------------|
| Engine 1 | 0.935 | 72/5 | 348.6 ms |
| Engine 2 | 0.948 | 73/4 | 316.9 ms |

Engine 2 wins on already-provided Lost & Found context. See `docs/engine-comparison.md`.

## 8. Analytics UI

Local route: `/admin/analytics` (Product / Engine / Evaluations). Empty states when no events. Not deployed to Cloud Run in this workstream.

## 9. Tests

`52 passed` unit/integration tests.

## 10. Known limitations

- GCS JSONL append is best-effort (race under multi-instance).
- Step-level guided drop-off chart is approximate (abandon = started − completed).
- Engine 2 LLM extraction only when heuristics weak and key present.
- Correction eval case still failing; FAQ soft paraphrases fail offline without LLM.
- Cost estimates incomplete without live token accounting.

## 11. Config

- Admin engine selection (default Engine 1)
- `GUIDED_ENABLED`
- Optional `ANALYTICS_HASH_KEY` (else `SECRET_KEY`)
- Eval live mode: `--live-model` + API key

## 12–13. Deploy / rollback

**Not deployed. Not merged to main.**

Rollback when deployed: switch Admin engine to Engine 1, or prior Cloud Run revision / git tag.
