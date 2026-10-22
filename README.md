# North Dakota LGBTQ+ Legislative Watch

A public, plain-English dashboard that follows North Dakota legislation that may
affect LGBTQ+ people. It answers, for each bill: what it is about, what it would
change, where it is in the process, whether a hearing is scheduled and how to
testify, how legislators voted, and whether it became law.

- **Official data only.** Every fact comes from the North Dakota Legislative
  Branch (ndlegis.gov) and links back to it.
- **Finds bills by their text, not just their titles.** HB 1430 (2025), titled
  only "regulation of social workers", is found because its text mentions sexual
  orientation, gender identity and conversion therapy.
- **Monitors itself.** A scheduled job checks the official sources hourly during
  sessions, records only real changes, and the dashboard shows when data was
  last checked and warns when it is stale.
- **No account, no tracking, no AI required.** Following bills is stored only in
  the visitor's browser.

## How it fits together

```
GitHub Actions (hourly, :17)          PostgreSQL                 Streamlit Community Cloud
python -m ndwatch monitor  ──write──►  bills, actions,  ◄──read──  streamlit_app.py
  1 discover assemblies/sessions       hearings, votes,            Overview · Bills · Hearings
  2 read official JSON API             testimony, events,          Recent Activity · Following
  3 compare, record changes            source checks               About & Sources · Reviewer
  4 read bill text, testimony pages
  5 relevance detection
```

| Folder | What it does |
|---|---|
| `ndwatch/sources/` | Official API connector, polite HTTP client, HTML/PDF readers |
| `ndwatch/db/` | Database tables (SQLAlchemy); SQLite locally, PostgreSQL hosted |
| `ndwatch/ingest.py` | Stores records idempotently and detects changes (events) |
| `ndwatch/process.py` | Builds a bill's real path (either chamber first, amendments, conference, veto…) |
| `ndwatch/relevance/` | Layered topic detection; rules in `topics.yaml` |
| `ndwatch/monitor.py` | One monitoring cycle, polling policy, health check |
| `ndwatch/explain.py` | Plain-language wording and glossary |
| `ndwatch/ui/` | Dashboard pages, theme, browser-only "following" storage |
| `tests/` | Synthetic unit tests and real 2025 validation tests |
| `docs/` | Source findings, deployment steps |

## Run it on your computer

Needs Python 3.11+.

```bash
git clone https://github.com/MOREDataset/nd-lgbtq-legislative-watch
cd nd-lgbtq-legislative-watch
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[app,dev]"

python -m ndwatch monitor --force  # first load: about 2–5 minutes, saves to data/ndwatch.db
streamlit run streamlit_app.py     # opens the dashboard at http://localhost:8501
```

Run `python -m ndwatch monitor --force` again whenever you want fresh data
locally; bill texts are read 1000 per run, so repeat it a few times (or set
`NDWATCH_MAX_PDFS_PER_RUN=2000`) to complete full-text detection.

Settings are environment variables; see `.env.example`.

## Tests

```bash
pytest          # 52 tests, no network needed
ruff check .
```

- `tests/test_historical_2025.py` uses **real** archived 2025 records (HB 1144,
  HB 1217, HB 1430, SB 2307, HB 1001) stored in `tests/fixtures/historical/`
  with their source URLs and retrieval times in `PROVENANCE.json`.
- Every other test uses **synthetic** data from the fictional "99th Assembly
  (2097)" with bill numbers in the 9000s, so it can never be confused with real
  records (`tests/fixtures/synthetic/`).

Covered: parsing, missing and malformed data, sponsor and vote extraction,
hearing extraction and rescheduling, removed hearings, amendments and new
versions, status transitions, bills that become law, fail, or are vetoed, new
bill detection, duplicate prevention on re-runs, temporary source failures, a
new assembly with no bills yet, and relevance detection from bill text.

## Reviewing bills

Bills with weaker matches are "possibly related" and wait for a person. With
`NDWATCH_ADMIN_PASSWORD` set, the dashboard shows a **Reviewer** page where you
include or exclude a bill with a written reason, optionally describe the
possible effect (expands / restricts / administrative / mixed / unclear), and
write a plain-language summary. Decisions and reasons are shown publicly on the
bill page. From the command line:

```bash
python -m ndwatch review list
python -m ndwatch review include --bill 202501:HB1430 --reason "Text addresses counseling on sexual orientation and gender identity" --impact restricts
```

To adjust what is detected, edit `ndwatch/relevance/topics.yaml` and change its
`version`; every bill is re-checked on the next run.

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): costs, required accounts, secrets,
and step-by-step setup for PostgreSQL, GitHub Actions and Streamlit Community
Cloud.

## Sources and known limits

See [docs/SOURCES.md](docs/SOURCES.md). In short: the API has no floor calendar
or vote schedule (we never predict vote dates), testimony and the testimony
deadline rule come from official web pages, and the app only states an
effective date the official record supports.

## Trust rules the code follows

- Missing data is shown as missing ("No upcoming event has been officially
  announced"), never filled in.
- Committee recommendations are never shown as votes; sponsors are never
  assumed to have voted a certain way.
- A hearing is never treated as a vote date.
- Passing one chamber is never shown as becoming law.
- Official text, our plain-language explanations, reviewer notes and any AI
  text are labeled separately.
- Content from official pages is treated as untrusted input: it is escaped
  before display and never executed or followed as instructions.

## License

MIT. Legislative data is public information from the North Dakota Legislative
Branch.
