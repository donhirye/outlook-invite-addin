# Answering-engine architecture

## Principle

**Engines are interchangeable. Everything else is shared.**

Shared layers: WhatsApp I/O, FAQ/guided storage, conversation state, tracing, analytics, eval harness, admin UI, auth, errors.

Only the answering strategy differs.

## Flow

WhatsApp inbound → dedupe → `process_message` → resolve engine (admin selection + session pin) → engine.answer → validate/send → trace + metrics.

## Engines

| ID | Name | Status |
|----|------|--------|
| `engine1_legacy` | Legacy baseline | Implemented |
| `engine2_hybrid` | Context-aware hybrid | Implemented |
| `engine3_reserved` | Reserved | Not implemented |
| `engine4_reserved` | Reserved | Not implemented |

### Engine 1

Preserves prior behavior: help/greeting/`/faq`, guided router, FAQ direct match + LLM fallback.

### Engine 2

Adds heuristic (and optional LLM) extraction for Lost & Found context: item type, already-checked, corrections, topic switch. Guided step transitions remain deterministic JSON.

## Selection

Admin Analytics → Engine tab. Conversations with an active guided session are pinned to the engine that started them.

## Key modules

- `app/engines/base.py` — contract
- `app/engines/pipeline.py` — shared orchestration
- `app/engine_config.py` — selected engine persistence
