# Engine comparison (actual harness results)

Dataset: `v1` (77 cases). Mode: `deterministic_mocked_safe` (no live model spend).

| Engine | Passed | Failed | Pass rate | Avg latency ms |
|--------|--------|--------|-----------|----------------|
| engine1_legacy | 72 | 5 | 0.935 | 348.6 |
| engine2_hybrid | 73 | 4 | 0.948 | 316.9 |

### Notable differences

- **already_provided_context** (“lost PE shirt… already checked both places”): Engine 2 passed (skip path); Engine 1 failed expected skip/office fact.
- Shared FAQ paraphrases still miss some soft fact checks when offline LLM is empty (both engines).
- Correction case still needs hardening (failed on both in this run).

These are harness results, not production A/B traffic.
