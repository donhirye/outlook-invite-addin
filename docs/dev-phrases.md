# Short phrases for Cursor (laptop or mobile)

A project skill teaches the agent these stages: `.cursor/skills/whatsapp-bot-dev-flow/SKILL.md`

| You say | What Cursor should do |
|---|---|
| **I want to write some new code** | Update `main`, create a feature branch, implement + test (no commit/push/deploy) |
| **Ready to check this in** | Save a **local** commit (laptop) or branch commit (cloud). Not production. |
| **Move this to GitHub** | Push the feature branch and open/update a **PR to `main`**. No merge/deploy unless you ask. |
| **Deploy** | Merge to `main` (if needed, with your OK) → GitHub Actions → Cloud Run |

Order that reaches real users:

`code on feature branch → check in → GitHub PR → merge to main → deploy`

Mobile uses the same phrases; Cursor runs a Cloud Agent instead of your laptop checkout.
