# Evaluation harness

## Location

`evals/` — offline, no WhatsApp sends.

## Dataset

`python -m evals.build_cases` → `evals/cases/dataset_v1.json` (≥75 cases).

## Run

```bash
cd whatsapp-hello-bot
python -m evals.run --engine engine1_legacy
python -m evals.run --engine engine2_hybrid
python -m evals.run --engine all
python -m evals.run --engine all --live-model   # explicit; cost-capped intent
```

Default mode clears live OpenAI unless `--live-model` (uses `OPENAI_API_KEY_EVAL` / env carefully). Reports label mocked vs live.

## Outputs

- `evals/reports/latest_summary.json` (shown in Admin → Analytics → Evaluations)
- Per-engine JSON reports + `evals/reports/history/`

## Scoring

Route, flow, required facts, forbidden claims, `[DEMO ANSWER]` when required. Engine-2-only extraction/transition checks where annotated.
