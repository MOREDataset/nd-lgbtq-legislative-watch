# Official sources and assumptions

Phase 1 findings. Everything here was checked against live responses from
ndlegis.gov on **2026-10-21** (raw samples are produced by the
"Collect source samples" workflow and saved on the `source-samples` branch).
When something below is an assumption rather than a verified fact, it says so.

## 1. JSON API (primary source)

Documentation: <https://ndlegis.gov/legislative-api-documentation>. No API key.
No rate limit is published; we use one request every 1.5 s and identify
ourselves with a descriptive User-Agent. `robots.txt` does not disallow any
path we use.

| Endpoint | What we use it for | Observed size (69-2025) | `Last-Modified` header |
|---|---|---|---|
| `/api/data/assemblies.json` | Discover assemblies and sessions (never hardcoded) | 5 KB | yes |
| `/api/assembly/{year}/data/sessions.json` | Session list, `current` flag, start dates | 1 KB | yes |
| `/api/assembly/{year}/data/bills.json` | Bills with sponsors, actions, versions, hearings | 7.8 MB | yes, updated several times a day |
| `/api/assembly/{year}/data/members.json` | Party, district, profile URL for sponsors and voters | 30 KB | yes |
| `/api/assembly/{year}/data/roll_call.json` | Individual legislator votes | 10.7 MB | yes |
| `/api/assembly/{year}/data/committees.json` | Not used yet | 135 KB | yes |
| `/api/data/century_code.json` | Not used yet (see 6) | 70 MB | yes |

### Verified formats

- `assemblies.json` is an **object keyed by assembly number** (`"69": {...}`),
  covering the 62nd–69th assemblies. Each entry has `assembly_year` (e.g.
  `"69-2025"`), which is the path segment for all other endpoints, and
  `sessions[]`. Only sessions carry a `current` flag.
- Session ids look like `"202501"` (year + sequence). The 69th Assembly has
  Organizational `202500`, Regular `202501`, Special `202502` (Jan 2026, folder
  `special`), Special `202503` (Sep 2026, folder `special-2`, `current: true`).
- `bills.json` is an object keyed by bill number. One file holds **all sessions
  of an assembly** (1,106 bills: 1,089 regular, 12 + 5 special). We never use the
  key for identity: a bill's id is `"{session_id}:{name}"`, e.g. `202501:HB1144`.
- Datetimes have **no time zone**. We assume they are Bismarck local time
  (America/Chicago). Action dates use the placeholder time `23:59:59` when only
  the day is known; we store a "date only" flag and never show a made-up time.
- Actions with a recorded vote carry a `roll_call` summary; otherwise `{}`.
- Action `category` values seen (2025): Introduced, Introduced (emergency),
  Committee hearing, Committee report, Amendment adopted, Passed, Failed,
  Received from House/Senate, Returned to House/Senate, Rereferred, Concurred,
  Not concurred, Conference committee, Delivered to Governor, Governor signed,
  Governor signed (Item veto), Vetoed by Governor, Veto sustained, Consideration
  of Governor's veto, Filed with Secretary of State, Withdrawn, Emergency clause
  carried/failed, Division of bill/amendment, Laid over, Reconsider, and others.
- `bills[].versions` includes both full bill versions (INTRODUCED, FIRST
  ENGROSSMENT, Enrollment…) and **amendment documents** ("Adopted by the …
  Committee", "Prepared by the Legislative Council staff for …"). "Prepared by"
  means proposed, not necessarily adopted; the app labels them that way.
- `versions_url`, `actions_url`, `hearing_url`, `testimony_url` and `video_url`
  are missing a slash (`https://ndlegis.govassembly/...`). We repair exactly
  that and nothing else.
- Some action descriptions contain a date that differs by a day from the
  action's `date` field (e.g. HB 1144 "Signed by Governor 05/01" dated 05/02).
  We show the official description verbatim next to the date.
- `passed` is `true`/`false`, and agrees with our own reading of the actions for
  every 2025 bill (608 became law, 426 failed, 4 vetoed, 37 resolutions
  adopted, 30 withdrawn).

### Roll calls

`roll_call.json` lists recorded **floor** votes (ids like `202501H00291`), with
`member_votes[]` (`Yea`, `Nay`, `Absent`). Committee recommendations ("do pass
8 3 2") appear only inside action descriptions; the app presents them as
committee recommendations, never as votes.

## 2. Supplemental pages (HTML)

| Page | Why needed | Parser |
|---|---|---|
| `…/bill-testimony/bt{n}.html` | Testimony is **not** in the API | `parse_testimony_page` |
| Public hearing schedule `www.ndlegis.gov/legend/committee/hearings/public-schedule/` | The **testimony deadline rule** and the official "how to submit" guide | `parse_public_schedule` |
| Bill text PDFs (`versions[].document_url`) | Full-text relevance detection | `extract_pdf_text` (pypdf) |

Testimony table columns (verified): Hearing Date, Time, Committee, Name,
Organization, Role, City State, Position (`In Favor`, `In Opposition`,
`Neutral`), Document Number (link to the PDF). Duplicate submissions are
sometimes packed into a nested table; the parser handles this (HB 1144:
112 documents, matching the page). The page warns that testimony "is updated
periodically and might not represent a complete record"; the app repeats this.

Testimony deadline: in October 2026 the schedule page says testimony for public
hearings is due one hour before the hearing starts, and that testimony is not
taken online for committee work sessions. The app **reads this sentence from
the page on every run** and quotes it with the date it was checked, so a
changed rule is picked up automatically.

## 3. What the API does not provide (and what we do about it)

- **Future floor calendars / vote dates**: not in the API. We never predict
  vote dates. The House/Senate daily calendars
  (`/legend/chamber_calendar/view/?chamber=H|S`) are a possible later
  collector.
- **Hearing schedule changes**: hearings come from `bills[].hearings`. A
  hearing that disappears is kept and marked "no longer on the official list",
  never deleted.
- **Bill subject index**: not exposed in the API; relevance uses title,
  summary and bill text instead.
- **Effective dates**: not a field. The app only repeats what the title says
  (e.g. "declares an emergency") and links to the session laws.

## 4. Freshness

`bills.json` had `Last-Modified` 2026-10-21 17:43 GMT when sampled, so it is
regenerated during the day even outside a session. Each run records, per
source: when we checked, HTTP status, the source's own `last_updated`, and a
content hash. Unchanged files are detected by hash and cause no work.

## 5. Session states the app handles

- An assembly whose `bills.json` returns 404 (expected right after a new
  assembly appears, e.g. 70-2027 before prefiling): recorded as "no bills
  published yet", not an error.
- Sessions with no bills, special sessions, and several sessions in one file.
- Historical assemblies (no current session, not the newest): refreshed at most
  once a day.

## 6. Not used yet

- `century_code.json` (70 MB). Layer C of relevance detection (bills that change
  a Century Code section whose current text mentions a topic) is implemented in
  the detector but not fed yet, because downloading 70 MB hourly is wasteful.
  Plan: a weekly job that stores only matching sections.
- `committees.json`.
