# 03 — FAQ retrieval (match + tiny RAG)

## What production does

1. Try to match a parent question to explicit `Q:` / `A:` pairs in the FAQ
2. If needed, chunk the FAQ, embed chunks, retrieve top-k similar chunks (RAG)
3. Ask the LLM to answer **only** from those excerpts
4. For small FAQs, production can skip embeddings and send the whole FAQ

Learning version: **no OpenAI calls**. You will implement lexical matching + a tiny bag-of-words retriever.

## Production files to read

- `whatsapp-hello-bot/app/faq_service.py` — `parse_faq_qa_pairs`, `match_faq_qa`, `answer_faq_question`
- `whatsapp-hello-bot/app/faq_rag.py` — `chunk_faq_text`, `retrieve_chunks`
- `whatsapp-hello-bot/app/faq_store.py` — durable FAQ load/save (GCS in prod)

## Your exercise

Implement TODOs in `exercise_03.py` using `../data/sample_faq.txt`.

```powershell
cd learning
.\.venv\Scripts\python.exe -m pytest 03-faq-retrieval -q
```

## Compare afterward

Production uses embeddings + cosine similarity. Your learning retriever uses token overlap only — same shape, cheaper intuition.
