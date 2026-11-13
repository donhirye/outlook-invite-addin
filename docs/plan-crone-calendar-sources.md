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

### 1. Per-event source footer for calendar answers — `[ ]`
When the calendar answers about a **specific event**, build the footer from that event’s own `source_name` and `source_url`.  
For general / non-event answers (e.g. “is there school today?” with no single event), keep the calendar-wide footer.  
Result: calendar behaves like the FAQ (source follows the answer).

**Not started — deliberately not doing this yet; more items to add first.**

### 2. Import Crone events as additional calendar events — `[ ]`
- Convert the Crone important-dates list into the existing calendar CSV import shape.
- Source Name: `2026-2027 Crone Middle School Calendar of Important Dates`
- Source URL: the Google Doc link.
- Import via the existing upsert path so D204 events stay and Crone events are added.
- Put times in `Notes` (no dedicated time field today).
- Keep **tentative** items marked tentative in notes (e.g. Career Night, Last Day of School).
- Ship to the production calendar store (admin import / GCS), not just a local file.

### 3. Overlaps between D204 and Crone — `[ ]` (decide first)
Known overlaps / near-overlaps:
- Parent/Teacher Conferences: D204 has 11/2 and 3/15; Crone also lists 10/22 (with times) plus 11/2 and 3/15.
- First / last day of school may appear in both.

Open decision: keep Crone rows as separate events (with times) vs prefer one row when names/dates match. Today there is no merge and no dual-source citation.

### 4. Other items — `[ ]`
_To be added — more coming._

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
