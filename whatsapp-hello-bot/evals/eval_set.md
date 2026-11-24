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

---

## EV-002 — Last day of school

**Status:** pinned / answer-focused  
**Priority:** calendar correctness

### Prompt
When’s the last day of school?

### Expected answer facts
- `May 28, 2027`
- `Tentative`

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Human gold: Last Day of School: Friday, May 28, 2027 (Tentative). Source/link ignored for scoring.

---

## EV-003 — Spring break

**Status:** pinned / answer-focused  
**Priority:** calendar correctness

### Prompt
When’s spring break?

### Expected answer facts
- `2027-03-29` (or equivalent: March 29, 2027)
- `2027-04-02` (or equivalent: April 2, 2027)
- `No School` (student attendance)

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Human gold: Spring Break is 2027-03-29 through 2027-04-02 (student attendance: No School). Source/link ignored for scoring.

---

## EV-004 — 8th grade dance

**Status:** pinned / answer-focused  
**Priority:** calendar correctness

### Prompt
When a the 8th grade dance

### Expected answer facts
- `May 14, 2027`
- `6pm-8pm` (or equivalent time range)

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Human gold: 8th Grade Dance: Friday, May 14, 2027 (6pm-8pm). Source/link ignored for scoring. Prompt kept as typed (typo intentional for real-user phrasing).

---

## EV-005 — Chromebook drop-off / missing device

**Status:** pinned / answer-focused  
**Priority:** FAQ correctness

### Prompt
Can I drop my kids Chromebook to school

### Expected answer facts
- child notifies teacher and school office
- technology team opens a missing-device report
- update within two school days
- contact the school office for drop-off / other arrangements

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Human gold: ask your child to notify their teacher and the school office; the school technology team will open a missing-device report and provide an update within two school days. If you need to drop off a device or make other arrangements, contact the school office.

---

## EV-006 — Party in the Park

**Status:** pinned / answer-focused  
**Priority:** calendar correctness

### Prompt
when is the party in the park?

### Expected answer facts
- `May 27, 2027`
- `8:30am-10:30am` (or equivalent)
- `7th Grade` (event is for 7th grade)

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Human gold: Party in the Park (7th Grade): Thursday, May 27, 2027 (8:30am-10:30am). Source ignored for scoring.

---

## EV-007 — Next PTSA Crone meeting

**Status:** pinned / answer-focused  
**Priority:** calendar correctness

### Prompt
when is the next PTSA crone meeting

### Expected answer facts
- `Jan 14, 2027` (or equivalent: January 14, 2027)
- `10:30am`

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Human gold: Thursday, Jan 14, 2027 (10:30am). Source/link ignored for scoring. “Next” is relative to eval `today`; pin assumes a date before Jan 14, 2027.

---

## EV-008 — NVHS / Class of 2031 shirts (what + pickup)

**Status:** pinned / answer-focused  
**Priority:** FAQ correctness

### Prompt
i heard about NVHS shirts - what is that? where an i pick it ?

### Expected answer facts
- Class of 2031 NVHS Wildcat shirt (or equivalent identification)
- order URL: `storessimple.com/crpromotions/45611`
- sales open through `December 15, 2026`
- pickup: Wildcat Wear store during Class of 2031 Wildcat Welcome on `January 13, 2027`
- contact: `nvhswildcatwear@gmail.com`

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Human gold covers order link, deadline, pickup place/date, and email. Prompt kept as typed (typos intentional).

---

## EV-009 — Who is Melissa Couch

**Status:** pinned / answer-focused  
**Priority:** FAQ / identity

### Prompt
Who is Melisssa couch

### Expected answer facts
- principal of Crone Middle School

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Human gold: she is principal of Crone Middle School. Prompt kept as typed (misspelling intentional).

---

## EV-010 — How the chatbot works

**Status:** pinned / answer-focused  
**Priority:** onboarding / meta

### Prompt
How does this thing work? Like the chatbot

### Expected answer facts
- identifies as PTSA chatbot (for this school / event)
- answers based only on PTSA organizer-provided information
- if unknown → ask an admin/organizer (e.g. in group chat)
- invite to send a question (example ok, e.g. parking)

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Human gold is the welcome / how-it-works blurb. Exact wording may drift; score intent of the four bullets above.

---

## EV-011 — Yearbook (where to find / order)

**Status:** pinned / answer-focused  
**Priority:** FAQ correctness

### Prompt
My son needs a book with all of those students and events that they give us where to find this and where to get?

### Expected answer facts
- interprets as yearbook (or equivalent)
- order via school office or approved online portal
- orders close `March 15, 2027`
- no order link / pickup details in FAQ → contact school office or PTSA for current link and pickup info

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Human gold is the yearbook FAQ answer. Soft paraphrase prompt; must not invent an order URL.

---

## EV-012 — Lost water bottle / Lost & Found

**Status:** pinned / answer-focused  
**Priority:** FAQ / guided correctness

### Prompt
Daughter left water bottle at school, where should she look?

### Expected answer facts
- two Lost & Found locations
- cafeteria / lunchroom
- outside the gym
- if not found: check both again, then school office

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Human gold: check cafeteria/lunchroom and outside gym; then recheck both and office. Soft lost-item paraphrase.

---

## EV-013 — Weather today (out of scope)

**Status:** pinned / answer-focused  
**Priority:** unknown / refuse inventing

### Prompt
How is weather today?

### Expected answer facts
- does not know / not in FAQ (or equivalent: couldn’t find that information)
- direct parent to contact PTSA administrators (or school/organizer contact)

### Forbidden
- inventing a forecast, temperature, or weather condition

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Human gold: I couldn't find that information in the event FAQ. Please contact the PTSA Administrators.

---

## EV-014 — 6th grade orchestra concert (answer only, no multi-event dump)

**Status:** pinned / answer-focused  
**Priority:** calendar / FAQ precision (RAG / FAQ match)

### Prompt
When is 6th grade orchestra concert?

### Observed bad behavior
Matched multi-event FAQ `WEEKLY-20261113-005` (“What upcoming Crone music events are scheduled?”) and returned the **entire** answer, including the unrelated Dec 8 holiday / BCO Honors concert.

### Expected answer facts
- `December 2, 2026` (or equivalent: Dec 2, 2026 / 2026-12-02)
- `7:00 PM` (or `7pm` / equivalent)
- 6th grade (band and/or orchestra concert naming ok)

### Forbidden
- first-semester holiday concert / `December 8` / `BCO Honors` (sibling events from the same FAQ row)
- Dumping the full multi-event FAQ answer when the ask is for one concert only

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Human gold: The 6th grade band and orchestra concert is scheduled for Wednesday, December 2, 2026, at 7:00 PM.  
Root cause pin: curated FAQ bundles multiple music events; bot must answer only the asked event.

---

## EV-015 — What’s going on in May

**Status:** pinned / answer-focused  
**Priority:** calendar overview

### Prompt
what all events are there in may?

### Expected answer facts
Must surface these May 2027 items (dates + names; phrasing may vary):
- `2027-05-13` — General PTSA Meeting
- `2027-05-14` — 8th Grade Dance
- `2027-05-15` — Fine Arts Fest
- `2027-05-27` — Party in the Park (7th Grade)
- `2027-05-28` — Last Day of School
- `2027-05-31` — Memorial Day
- `2027-05-29` (or May 29–30) — Louis trip

(Full phrasing may vary; do **not** score Source / Link / calendar document titles.)

### Notes
Human gold is a May overview listing. Score event coverage, not formatting or source labels.

---

## EV-016 — December deadlines / events, skip sports

**Status:** pinned / answer-focused (behavior + coverage; no single gold string)  
**Priority:** calendar + FAQ overview with filter

### Prompt
what deadlines exist for december? skip the sports ones

### Expected behavior
1. Pull **December** items from **both** calendars (Crone + District 204).
2. Pull **December** items / deadlines from the **FAQ**.
3. **Exclude sports** — e.g. wrestling, swimming, basketball, and other athletic meets/games.

### Expected answer facts (non-exhaustive examples of in-scope Dec items)
- Winter Break (district calendar; starts ~`2026-12-21`)
- NVHS / Class of 2031 shirt sales deadline (`December 15, 2026`) when treated as FAQ deadline
- Non-sports Dec FAQ/calendar items as available (e.g. concerts, Giftmart end, Christmas Carol trip) — exact set may evolve with data

### Forbidden
- wrestling / swimming / basketball (and similar sports schedule items) in the reply

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Not an exact-string gold answer. Score: December coverage from calendars + FAQ, minus sports.

---

## EV-017 — How do I order PE shirts? (Boomer Tees only)

**Status:** pinned / answer-focused  
**Priority:** FAQ / RAG coverage + precision

### Prompt
how do I order PE shirts?

### Observed bad behavior
Missed Crone newsletter **2026-08-14** (Boomer Tees ordering link + limited $8 prior-style supply at Back to School Days). Instead answered from stale/related FAQs: replacement PE uniforms via school office ($15) and chorus/band/orchestra performance polos via activity director — and dumped both.

### Expected answer facts
- Boomer Tees (new PE shirt vendor / ordering process)
- Order / pick up at Boomer Tees (link ok if present)
- Optional: limited previous-style supply at Crone during 7th/8th Back to School Days for `$8` / exact change

### Forbidden
- performance polos / chorus / band / orchestra polo ordering
- PushCoin / activity director (polo path)
- Treating this as only “replacement PE uniform via school office for $15” when Boomer Tees ordering guidance exists

(Full phrasing may vary; Source should be the Aug 14 weekly / real newsletter, not a dummy label.)

### Notes
Human gold (from Crone newsletter 2026-08-14): PE shirts now ordered through Boomer Tees; use the Boomer Tees link to order and pick up. Limited prior-style supply at Crone during 7th/8th Back to School Days for $8 (exact change).  
Root cause pin: (1) Aug 14 PE shirt content not in FAQ corpus → wrong near-miss FAQs; (2) answer path blends related shirt/polo rows instead of PE-only.

---

## EV-018 — Is the Reflections competition over? (use dates vs today)

**Status:** pinned / answer-focused  
**Priority:** FAQ timing / stale status rows

### Prompt
is the reflections competition over?

### Observed bad behavior
Treated a stale status FAQ (“screening process … underway … results are awaited,” Oct 14) as current, and answered that the FAQ does not say the competition is finished — instead of comparing known Reflections dates to today and saying the school-level phase is over.

### Expected answer facts
- Yes / over / finished for the Crone school-level Reflections phase (phrasing may vary)
- Grounding in dated FAQ facts vs today, e.g.:
  - submission deadline `October 9, 2026` has passed, and/or
  - judging `November 12, 2026` has passed, and/or
  - Crone entries already advanced to district (Oct 28 newsletter)

### Forbidden
- Saying screening is still underway / results still awaited as if that were current status
- Claiming the FAQ has no way to tell whether the school-level competition is over when dated FAQs exist

(Full phrasing may vary; do **not** score Source / Link.)

### Notes
Human gold (as of late Nov 2026): Yes — Crone Reflections submission/judging is over (deadline Oct 9; judging Nov 12); entries advanced to district. District-level may continue.  
Root cause pin: timing asks skip raw Q/A paste and go RAG+LLM; a dateless “status underway” chunk outranks / confuses use of submission & judging dates vs TODAY.
