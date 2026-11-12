# Backlog list

Single product backlog for the WhatsApp PTSA assistant.  
Add new ideas here (short-term or long-term). Do not start a second parallel list.

**How to use:** newest or active work near the top of each section. Mark done with `[x]` and a short note (date / PR) when shipped. Keep deferred items `[ ]`.

---

## Short-term (next / soon)

### Product / beta readiness
- [ ] Dedicated production WhatsApp Business number (not personal 812)
- [ ] Register production number in Meta Cloud API; update `WHATSAPP_PHONE_NUMBER_ID` + lasting access token on Cloud Run
- [ ] Switch Meta app Development → Live; finish privacy policy / required app settings
- [ ] Replace test `wa.me` link with production number in admin (prefill kept)
- [ ] Confirm any parent in a shared group can tap the link → greeting + answers (path A: private 1:1)
- [ ] Stronger admin password than default; no demo secrets in production
- [ ] Move WhatsApp/OpenAI secrets to Secret Manager (or equivalent)
- [ ] Basic monitoring: webhook failures, deploy failures, `/health`
- [ ] Written support path when the bot doesn’t know (who parents should ask)
- [ ] FAQ ownership: who edits `/admin/faq`, GCS FAQ backup expectation

### Product / analytics (Phase 2+)
- [ ] Track poster / `wa.me` clicks (not only inbound messages) — Phase 1 analytics notes this gap
- [ ] Revisit Phase 2 Product KPIs that were hidden (guided completion, resolution, feedback, etc.) when traffic supports them

### Engineering (deferred from recent work)
- [ ] Revisit **RAG** for FAQ once the combined FAQ grows past the full-text path (`FAQ_SKIP_RAG_MAX_CHARS` raised to 30k for now — “worry about RAG later”)
- [ ] **Calendar LLM fallback** (same shape as FAQ: deterministic match → calendar-only LLM) — explicitly deferred; deterministic holiday phrasing shipped first
- [ ] Admin UI for **policies** (privacy copy, not-found text) instead of only `app/config.py` constants
- [ ] Stronger student-name PII detection beyond regex (privacy filter shipped for ID/phone/email / “student named…” patterns)

### Quality / ops (soon after beta)
- [ ] Tighten Cloud Run deploy SA permissions (narrow storage roles)
- [ ] Rotate tokens that may have appeared in old source archives
- [ ] Rate limiting / abuse basics on webhook
- [ ] Business verification / higher messaging limits if volume grows

---

## Longer-term

- [ ] Optional public FAQ page with per-question anchors
- [ ] Simple onboarding for a **second event/PTSA** (separate FAQ and/or number)
- [ ] Multi-engine eval / comparison loop as a recurring practice (harness exists; keep using it)
- [ ] OpenTelemetry or richer distributed tracing (optional; Cloud Logging is enough for now)

---

## Explicitly out of scope (unless WhatsApp product changes)

- Bot as a **group member** answering in-thread
- `@bot` mentions inside WhatsApp groups

**Intended UX stays:** share `wa.me` in any chat → private 1:1 with the bot.

---

## Done (recent — keep short)

- [x] Structured FAQ + District 204 calendar CSV import + sourced answers
- [x] Durable Q&A traces (GCS) + higher analytics Q&A log limit
- [x] Full-FAQ path via `FAQ_SKIP_RAG_MAX_CHARS=30000` (RAG deferred)
- [x] Broader deterministic calendar (Dec/Jan, Christmas, New Year, holidays)
- [x] Strip model-invented `Source:` / remove italic `_Source_` markup
- [x] Student privacy filter (ID / phone / email / named-student asks) — PR #17, `c6df8ba`

---

## Notes

- Former `docs/beta-launch-list.md` content lives here so there is one list.
- When someone says “later / Phase 2 / don’t build yet,” **add a checkbox here** instead of relying on chat memory.
