# Beta Launch List

POC = what you’re running now (Meta test number, allowlisted phones, FAQ admin, `wa.me` link → private 1:1 chat, GitHub Actions deploy).

Beta = real parents in real groups can use the bot without being on a 5-person allowlist.

## Must-have for beta

1. **Dedicated production WhatsApp Business number** (not personal 812).
2. Register that number in Meta Cloud API; update `WHATSAPP_PHONE_NUMBER_ID` + lasting access token on Cloud Run.
3. Switch Meta app **Development → Live**; finish privacy policy / required app settings.
4. Replace test `wa.me` link with the production number in FAQ Settings (prefill kept).
5. Confirm **any** parent in a shared group can tap the link and get greeting + FAQ answers (path A: private chat).
6. Stronger admin password than default; don’t leave demo secrets in production.
7. Move WhatsApp/OpenAI secrets to **Secret Manager** (or equivalent), not plain env if possible.
8. Basic monitoring: webhook failures, deploy failures, `/health` check.
9. Written support path when the bot says it doesn’t know (who parents should ask).
10. FAQ ownership: who edits `/admin/faq`, backup expectation for GCS FAQ.

## Should-have soon after beta

11. Real **Google Docs** source link on answers (replace the placeholder).
12. Optional public FAQ page with per-question anchors (better than whole-doc links).
13. Business verification / higher messaging limits if volume grows.
14. Tighten Cloud Run deploy SA permissions (narrow storage roles).
15. Rotate tokens that may have appeared in old source archives.
16. Simple onboarding for a **second event/PTSA** (separate FAQ or separate number).
17. Rate limiting / abuse basics on webhook.

## Explicitly out of beta (unless WhatsApp product changes)

- Bot as a **group member** answering in-thread  
- `@bot` mentions inside WhatsApp groups  

Beta UX remains: **share `wa.me` in any chat → private 1:1 with the bot**.
