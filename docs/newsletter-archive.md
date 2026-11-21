# Crone PTSA newsletter archive

Offline workflow to archive Crone PTSA newsletters from Gmail and generate review artifacts.

**Not part of the live WhatsApp bot.** Nothing here is imported by `app.main`. Artifacts are drafts for human review — they are **not** auto-published or indexed into FAQ/RAG.

```
Gmail → ingest → immutable archive (HTML + metadata [+ EML])
                      ├─→ cleaned sections Markdown
                      ├─→ FAQ CSV + FAQ review report (draft; LLM extractor)
                      ├─→ reconcile → combined_FAQ.csv (+ reconciliation report)
                      └─→ review PDF
```

Base branch for this work: create feature branches from latest `main`.

## Setup (one-time, no paid Google Cloud resources required beyond your existing Drive)

### 1. Install optional Python deps

```powershell
cd whatsapp-hello-bot
.\.venv\Scripts\activate
pip install -r requirements-newsletter.txt
```

### 2. Google Cloud OAuth client (Desktop)

1. In [Google Cloud Console](https://console.cloud.google.com/) pick a project you control (can be a free personal project).
2. Enable **Gmail API** and **Google Drive API**.
3. Configure OAuth consent screen (External or Internal). Add your Google account as a test user if the app is in testing.
4. Create credentials → **OAuth client ID** → Application type **Desktop app**.
5. Download the JSON. Save it locally as:

```text
whatsapp-hello-bot/.secrets/google_oauth_client.json
```

Or set `GOOGLE_OAUTH_CLIENT_SECRETS` to that path.  
**Do not paste client secrets, tokens, or passwords into chat. Do not commit `.secrets/`.**

### 3. Configure `.env`

Add to `whatsapp-hello-bot/.env` (already gitignored):

```env
NEWSLETTER_DRIVE_PARENT_FOLDER_ID=1a7Lq5kjfckxn73RztFDpw0eSgOwwW53N
# Optional overrides:
# GOOGLE_OAUTH_CLIENT_SECRETS=C:\path\to\client_secret.json
# GOOGLE_OAUTH_TOKEN_PATH=C:\path\to\token.json
# NEWSLETTER_LOCAL_ROOT=C:\path\to\local\archive
# NEWSLETTER_DEFAULT_GMAIL_QUERY=subject:(Crone) newer_than:365d
```

The Drive parent folder ID is the last segment of:

`https://drive.google.com/drive/u/0/folders/1a7Lq5kjfckxn73RztFDpw0eSgOwwW53N`

Ingest creates **one subfolder per issue** under that parent. It does **not** change sharing permissions or make files public.

### 4. First OAuth login

The first ingest command opens a browser. Grant:

- `gmail.readonly` — read newsletter messages only
- `drive.file` — create/manage files this app creates under your Drive

A refresh token is stored at `whatsapp-hello-bot/.secrets/google_newsletter_token.json` (gitignored).

## Commands

Run from `whatsapp-hello-bot/` with the venv active.

### 1) Gmail ingestion

Dry-run (safe default — writes nothing except a local JSON report under `data/newsletter_archive/reports/`):

```powershell
python scripts/newsletter_ingest.py --query "subject:(Crone) (newsletter OR ""Weekly Newsletter"")" --dry-run
```

Or by label:

```powershell
python scripts/newsletter_ingest.py --label "Crone Newsletter" --dry-run
```

Confirmed write (local archive + Drive source files):

```powershell
python scripts/newsletter_ingest.py --query "subject:(Crone) (newsletter OR ""Weekly Newsletter"")" --confirm
```

Local archive only (skip Drive):

```powershell
python scripts/newsletter_ingest.py --query "..." --confirm --local-only
```

Equivalent module form:

```powershell
python -m newsletter_archive ingest --query "..." --dry-run
```

### 2–4) Artifact generators (no Gmail / no Smore)

Each generator reads `*_Source.html` + `*_Metadata.json` only. It does not overwrite the other artifacts’ *sources*; it only writes its own output file.

```powershell
$issue = "data\newsletter_archive\issues\Crone_PTSA_Newsletter_2026-11-11"

python scripts/newsletter_generate_sections.py $issue
python scripts/newsletter_generate_faq.py $issue          # LLM extractor (needs OPENAI_API_KEY)
python scripts/newsletter_generate_faq.py $issue --heuristic   # offline fallback
python scripts/newsletter_generate_pdf.py $issue
```

FAQ generation uses the canonical extractor prompt in `newsletter_archive/extractor_prompt.py`
(one issue at a time; parent-useful FAQs; CSV nine-column schema via the pipeline).

Incremental combine uses `newsletter_archive/reconciler_prompt.py` (system of record =
combined FAQ; semantic merge; provenance; conflict flags; change log).
It writes `*_FAQ.csv` plus `*_FAQ_Review.md` (date assumptions, privacy notes, section refs).
It does **not** merge into the live FAQ store — that is a separate reconciliation step.

### 5) Reconcile into combined FAQ

Folds candidate issue FAQ CSVs into `data/newsletter_archive/combined_FAQ.csv` (sibling of `issues/`), applying the reconciler rules in `newsletter_archive/reconciler_prompt.py` one newsletter at a time:

```powershell
python scripts/newsletter_reconcile_faq.py --reset `
  data\newsletter_archive\issues\Crones_Weekly_Newsletter_2026-10-30\Crones_Weekly_Newsletter_2026-10-30_FAQ.csv `
  data\newsletter_archive\issues\Crone_PTSA_Newsletter_2026-11-04\Crone_PTSA_Newsletter_2026-11-04_FAQ.csv `
  data\newsletter_archive\issues\Crones_Weekly_Newsletter_2026-11-06\Crones_Weekly_Newsletter_2026-11-06_FAQ.csv `
  data\newsletter_archive\issues\Crone_PTSA_Newsletter_2026-11-11\Crone_PTSA_Newsletter_2026-11-11_FAQ.csv
```

Writes:
- `data/newsletter_archive/combined_FAQ.csv`
- `data/newsletter_archive/combined_FAQ_Reconciliation.md`

**Conflict policy:** contradictory candidates stay classified as Conflict in the report (old vs new noted), but the combined CSV keeps the existing `FAQ_ID` and **writes the latest newsletter’s content**, with `Status=Needs_Review` so Active-only RAG does not silently trust unresolved conflicts.

Still offline from the WhatsApp bot — no auto-import into production FAQ. For staging Test Chat, import the combined CSV into the staging FAQ store (admin import or upload `faq_records.json` to the staging bucket) after review.

## Issue folder layout

Folder names come from the **email subject series** + issue date, so Weekly and PTSA do not share a folder:

- `Crones_Weekly_Newsletter_YYYY-MM-DD` ← subjects like “Crone's Weekly Newsletter”
- `Crone_PTSA_Newsletter_YYYY-MM-DD` ← subjects like “Crone PTSA Newsletter 11.18.2026”

```text
Crones_Weekly_Newsletter_2026-11-20/
  Crones_Weekly_Newsletter_2026-11-20_Source.eml
  Crones_Weekly_Newsletter_2026-11-20_Source.html
  Crones_Weekly_Newsletter_2026-11-20_Metadata.json
  Crones_Weekly_Newsletter_2026-11-20_Cleaned_Sections.md
  Crones_Weekly_Newsletter_2026-11-20_FAQ.csv
  Crones_Weekly_Newsletter_2026-11-20_FAQ_Review.md
  Crones_Weekly_Newsletter_2026-11-20_Review.pdf
```

- **`.eml`**: original RFC822 from Gmail `format=raw` when available.
- **`.html`**: stable snapshot used by all generators (never rebuilt from Smore).
- **FAQ CSV / cleaned MD**: potential future RAG experiment inputs after human review.
- **Review PDF**: human review/archive copy only — not primary RAG input.

## Weekly procedure

1. `python scripts/newsletter_ingest.py --query "..." --dry-run`  
   Check count, subjects, dates, duplicates/conflicts.
2. `python scripts/newsletter_ingest.py --query "..." --confirm`  
   Imports new messages only (idempotent by Gmail id + content hash).
3. For each new local issue folder, run the three generators independently.
4. Review FAQ CSV + PDF in Drive / locally. **Do not** import into production FAQ until approved.
5. Same `--query` / `--label` works for historical backfill and new weekly arrivals.

## Safety notes

- Ambiguous publication dates are flagged — no silent guessing; no archive write for those rows.
- Subject dates win for folder naming when the subject has exactly one date (including `11.11.2026` / `11/11/2026` forms). Body event dates are ignored in that case.
- Conflicts (same issue date, different content; same Gmail id, different hash) are reported and not overwritten.
- Student shout-outs / PII-looking blocks are skipped from Active FAQ drafts.
- Logs include message IDs and outcomes, not full newsletter bodies or credentials.
- Production WhatsApp deploy is unrelated and remains a separate, explicit Actions workflow.
