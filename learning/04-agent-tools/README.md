# 04 — Agent-style routing / tool calling

## What production does

The webhook does not always call the FAQ LLM. It routes each inbound text through a decision tree:

1. help/menu command → send help text
2. opener/prefill greeting → send PTSA intro
3. `/faq` admin command → maybe append FAQ (admin phones only)
4. otherwise → answer from FAQ

That is a simple **agent router**: inspect input, choose a tool/action, return a result.

More advanced agentic apps use LLM tool-calling APIs. Same idea: model picks a named tool, your code executes it, then the model continues.

## Production files to read

- `whatsapp-hello-bot/app/main.py` — branches inside `receive_webhook`
- `whatsapp-hello-bot/app/faq_admin.py` — command detectors + `/faq` parse
- `whatsapp-hello-bot/app/faq_service.py` — FAQ “tool”

## Your exercise

Implement `route_message()` in `exercise_04.py` so it returns a structured action:

- `{"action": "help"}`
- `{"action": "greeting"}`
- `{"action": "faq_admin", "question": ..., "answer": ...}` or `{"action": "faq_admin_usage"}`
- `{"action": "faq_answer", "question": ...}`

No network calls.

```powershell
cd learning
.\.venv\Scripts\python.exe -m pytest 04-agent-tools -q
```

## Compare afterward

Sketch how you would wrap each action as an OpenAI tool (`name`, `description`, JSON schema) if you upgraded this router to model-driven tool calling.
