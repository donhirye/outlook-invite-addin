# Pinned eval examples

Human-pinned regression cases. Not auto-run yet — capture intent here before wiring into `evals/cases/`.

---

## EV-001 — Never invent a dummy source label

**Status:** pinned / not implemented  
**Priority:** later (do not fix in code until asked)

### Prompt
Any FAQ / overview answer that would otherwise fall back to a placeholder source name.

### Observed bad behavior
Reply ended with:

```text
Source: Crone PTSA FAQ
```

That string is **not** a real document or newsletter. It is a hardcoded fallback in `format_parent_answer` when `source_name` is missing (`app/faq_admin.py`).

### Expected
- Never invent or attach a dummy/generic source such as `Crone PTSA FAQ`.
- If the matched FAQ row (or calendar row) has a real `Source` / `Source_URL`, use that.
- If there is no real source on the evidence, omit the Source line entirely (or say source unknown) — do **not** fabricate a brand-looking label.

### Notes
Caught 2026-11-22 after a December ask fell through to FAQ RAG instead of overview. Fix is deferred; this pin exists so we do not forget.
