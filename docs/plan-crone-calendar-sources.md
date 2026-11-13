# Plan: Crone Middle School calendar + per-event sources

Working plan for the next calendar work. **Nothing here is implemented yet.**  
This is a living doc: more items will be added as we talk through them. Move finished items to `docs/backlog.md` “Done” with the PR number.

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` shipped

---

## Goal

Add the **2026–2027 Crone Middle School Calendar of Important Dates** (Google Doc) to the school calendar, alongside the existing District 204 calendar, and have answers cite the **right source** for each event (like FAQ rows do).

Crone is the only additional source for now. Google Doc link will be used as the source URL for Crone events.

---

## Current behavior (why this plan exists)

- Calendar store holds events from the District 204 calendar CSV (holidays, breaks, no-school days).
- Each event can carry its own `source_name` / `source_url`, and CSV import already saves them per event.
- **But** calendar answers use one calendar-wide footer (`_source_footer()` → `get_calendar_meta()`), not the event’s own source. Import also overwrites the calendar-wide source with the last imported row’s source.
- FAQ answers attach the source from the FAQ row that answered. Calendar does not behave that way yet.
- If something exists in two places: calendar is checked **before** FAQ; calendar name matching returns the **first** hit; there is no merge and no dual-source citation.
- Re-importing the same start + end + name overwrites that one event (same `event_id`); different name/date adds a new event.

---

## Plan items

## Decision: do **A** now (split by ownership), defer **D**

- **A (in scope):** District 204 owns attendance (no school / breaks / holidays). Crone owns school events and times. They barely overlap, so no priority engine.
- **D (deferred):** cite both sources when they describe the same event. Only matters for a few overlaps (conferences 11/2 and 3/15; first/last day). Doing D without A delivers almost nothing, because the calendar cannot answer “when is event X” today — see findings below.

### Findings that shaped this (verified against current code)
- Calendar only answers date/break-style questions (“is there school on 11/2”, winter break, days until…). It has **no “when is event X” lookup**.
- `when are the parent teacher conferences` does **not** reach the calendar (gate regex needs `parent/teacher`, misses `parent teacher`).
- `when is the institute day` passes the gate but has **no answer branch**, so it falls through to the FAQ.
- `when is fall fest` does not reach the calendar and is not in the FAQ, so parents get “couldn’t find that”.
- **Collision risk:** `event_id` = hash of start + end + name. Crone’s “Parent/Teacher Conferences” on 11/2 and 3/15 would **overwrite** the District 204 rows (same name + dates) and wipe their “No School” attendance. Names must differ.
- The FAQ already has a “When is the next PTSA meeting?” entry that answers Nov 12 (now in the past) — overlaps with the Crone PTSA meeting dates.

---

## Plan items (A)

Do these in order. Likely one PR, then a post-deploy check. Status: all `[ ]` not started.

### A1. Collision-safe Crone import data — `[ ]`
- Convert the 27 Crone rows (reference table below) into the existing calendar CSV shape.
- Source Name: `2026-2027 Crone Middle School Calendar of Important Dates`; Source URL: the Google Doc link.
- Leave **Student Attendance blank** for Crone rows so they never change “is there school” answers.
- Put times in `Notes`. Mark tentative items tentative (Career Night, Last Day of School).
- Give Crone rows that share a name + dates with District 204 (Parent/Teacher Conferences 11/2, 3/15) a distinct name so they do not overwrite the district rows.
- Import via the existing upsert path. Do not touch the calendar-wide source when importing Crone rows.

### A2. Per-event source footer — `[ ]`
- When the calendar answers about a **specific event**, build the footer from that event’s own `source_name` / `source_url`.
- General / non-event answers (is there school today, months off, etc.) keep the calendar-wide footer.
- Result: Crone events cite the Doc; District 204 events keep citing the district PDF.

### A3. Calendar finds events by name — `[ ]` (biggest piece)
- Add a generic “match event name in the question → return date, time (from Notes), source” lookup.
- Widen the calendar gate for “when is …” / “next …” event phrasing (Fall Fest, Curriculum Night, PTSA meeting, Picture Day, socials, dances, Fine Arts Fest, Career Night, Den Days, Color Run, etc.).
- Fix the `parent teacher` (no slash) gate gap and give “institute day” a real answer branch.
- Recurring events (General PTSA Meeting): “next …” returns the next upcoming date.
- Events already past: answer with the date and say it has passed (uses America/Chicago “today”).

### A4. Fix hardcoded first/last day answers — `[ ]`
- “First day of school” currently says the calendar has no confirmed first day; Crone lists 8/17/26.
- “Last day of school” currently only looks for a tentative Teacher Work Day; Crone lists 5/28/27 (tentative).
- Answer from the Crone events (with source), keeping the tentative wording.

### A5. Tests — `[ ]`
- Name lookup and next-event behavior (including recurring PTSA meetings and past events).
- Per-event source footer (Crone vs District 204).
- Crone rows never change `is_school_day` results; conferences import does not overwrite District 204 rows.
- Routing: widening the calendar gate does not steal questions that the FAQ should answer.

### A6. Ship — `[ ]`
- Import the Crone CSV into the production calendar store (admin upload / GCS), then deploy from `main` via Actions.
- Post-deploy checks (real WhatsApp questions): “when is fall fest”, “next PTSA meeting”, “when are parent teacher conferences”, “when is the first day of school”, “is there school on 11/2”.

---

## Deferred

### D. Cite both sources when two describe the same event — `[ ]` deferred
- Conferences (11/2, 3/15) and first/last day. Needs same-event detection across sources and a two-source footer.
- Revisit after A ships.

### Other items — `[ ]`
_To be added — more coming._

---

## Open questions

1. **Google Doc link:** which exact URL goes in `Source URL`, and is the Doc shared so any parent can open it (“anyone with the link”)? It will be tapped from WhatsApp.
2. **FAQ vs calendar for “next PTSA meeting”:** the FAQ entry already answers it (and is stale: Nov 12). Calendar runs first, so once A3 ships the calendar wins. Should we retire/update that FAQ entry, or keep the FAQ as the winner for that question?
3. **Conference overlap wording (until D ships):** when a parent asks about conferences, which row do we show — Crone (with times) only, or all matching rows listed? Also what to name the Crone 11/2 and 3/15 rows to avoid the collision.
4. **Multiple matches:** for questions like “PTSA meetings” or “conferences,” list all upcoming dates, or just the next one?
5. **First/last day authority:** is Crone the authority for first and last day (8/17 and 5/28 tentative), replacing the “check the district PDF” wording?
6. **Times:** keep times in `Notes` for now, or add a dedicated time field to events?
7. **Other FAQ overlaps:** the FAQ also mentions Color Run registration and October conferences. Any other FAQ rows that duplicate calendar events and should be reconciled before widening the gate?

---

## Out of scope for this plan (for now)

- Calendar LLM fallback (already in backlog as deferred).
- Per-parent timezone (school timezone is America/Chicago; configurable timezone is a separate backlog item).

---

## Reference: Crone dates to import (from the Google Doc)

| Date | Event | Times |
|---|---|---|
| 8/7/2026 | New to District Orientation | 10am-12pm |
| 8/10/2026 | Den Days - 6th Grade | 8am - 12:30pm |
| 8/11/2026 | Den Days - 7th and 8th Grades | 8am - 12:30pm |
| 8/17/26 | First Day of School | 8:00am |
| 8/25/26 | 8th and 7th grade Curriculum Night | 6-8:15pm |
| 9/1/26 | Fall Fest | 3:10pm-4pm |
| 9/1/26 | 6th Grade and Encore Curriculum Night | 6-8pm |
| 9/10/26 | General PTSA Meeting | 9:30am |
| 9/10/26 | School Picture Day | All day |
| 9/25/26 | Color Run | TBA |
| 10/15/26 | General PTSA Meeting | 9:30am |
| 10/16/26 | 7th Grade Social | 6:00pm-8:00pm |
| 10/22/26 | Parent/Teacher Conferences | 4:30PM - 8:00PM |
| 11/2/26 | Parent/Teacher Conferences | 8am - 8pm |
| 11/12/26 | General PTSA Meeting | 9:30am |
| 1/14/27 | January PTSA Mtg | 10:30am |
| 2/11/27 | General PTSA Meeting | 9:30am |
| 2/19/27 | 6th Grade Social | 6:00pm-8:00pm |
| 3/15/27 | Parent/Teacher Conferences | 12:00pm-7:30pm |
| 3/18/27 | General PTSA Meeting | 9:30am |
| 4/15/27 | General PTSA Meeting | 9:30am |
| 4/28/27 | Tentative Career Night | (none listed) |
| 5/13/27 | General PTSA Meeting | 9:30am |
| 5/14/27 | 8th Grade Dance | 6pm-8pm |
| 5/15/27 | Fine Arts Fest | 9am-4pm |
| 5/27/27 | Party in the Park (7th Grade) | 8:30am-10:30am |
| 5/28/27 | Last Day of School | TENTATIVE |

Source doc: Google Doc `10WRr9ZPPmZiDH_a_2kz40TycyVIJ9eCGlIBAFL7hLIM` (link to be used as Source URL).
