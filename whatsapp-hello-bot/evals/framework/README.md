# Eval framework (answering-strategy bake-offs)

Reusable validation harness for comparing question-handling designs against the
same calendar / FAQ JSON / chunk stores.

## Designs

| ID | Meaning |
|----|---------|
| A  | Prod base: looks-like calendar gate → FAQ/RAG |
| C  | Overview + gated calendar → FAQ/RAG |
| E  | Dual-retrieve; merge whenever both hit |
| Ep | Dual-retrieve; calendar wins unless how-to merge |

## Enable

```bash
EVAL_FRAMEWORK_ENABLED=true
ANSWER_STRATEGY=Ep   # or A, C, E
```

With the flag **off**, Engine 1 always uses **Ep** (no switching).

## Reuse tomorrow

```python
from evals.framework import list_strategies, run_strategy, resolve_strategy_id
```

Strategies are implemented in `app/eval_framework/` so they can run on staging
Cloud Run. This `evals/framework/` package is the documented entrypoint for
harness / CSV scripts.

## CSV side-by-side (next)

Drop a prompts CSV → run each strategy → write results CSV. Not wired yet;
import from this package when you build it.
