# Deployment validation (not executed in this workstream)

**No Cloud Run deploy and no merge to main were performed for the multi-engine platform.**

## Before production

1. Merge `feature/multi-engine-platform` only after review.
2. Confirm `GUIDED_ENABLED` and selected engine (`engine_config` / admin Analytics).
3. Ensure GCS writable for: FAQ, guided packs, `analytics_events.jsonl`, `answer_traces.jsonl`, `engine_config.json`.
4. Run `python -m evals.run --engine all` and attach `latest_summary.json`.
5. Smoke: FAQ direct, guided start, Engine 2 skip path, cancel, metrics `/metrics`, Analytics tabs.
6. Rollback: set engine to `engine1_legacy` in Admin, or redeploy prior revision / tag `pre-guided-v1` as appropriate.

## Rollback

- Soft: Admin → Analytics → Engine → Engine 1.
- Hard: Cloud Run previous revision or git tag redeploy.
