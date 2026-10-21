# Deployment

Three pieces, each replaceable on its own:

```
 GitHub Actions (hourly)  ──writes──►  PostgreSQL (hosted)  ◄──reads──  Streamlit Community Cloud
 python -m ndwatch monitor                                              streamlit_app.py
```

The dashboard never contacts ndlegis.gov. If GitHub Actions or the Legislature's
site is down, the dashboard keeps serving stored data and shows a warning.

## Costs and limits (check current terms; free tiers change)

| Service | Plan | Expected cost | Limits that matter here |
|---|---|---|---|
| GitHub (public repo) | Free | $0 | Actions minutes are free for public repos. Scheduled runs can start several minutes late at busy times. GitHub turns off schedules after 60 days without repository activity; the workflows re-enable themselves daily. |
| PostgreSQL | Neon or Supabase free tier | $0 to start | About 0.5 GB storage. One assembly uses roughly 100–200 MB (mostly bill text and individual votes). Supabase pauses projects after a week without activity; hourly writes prevent that. If storage runs out, the paid tiers are about $19–25/month. |
| Streamlit Community Cloud | Free | $0 | Public apps only. The app sleeps after a period with no visitors; the next visitor wakes it (about 30 seconds). Around 1 GB memory. |

## Accounts and permissions you need

1. **GitHub**: you already own the repo. Nothing else.
2. **A PostgreSQL provider** (Neon recommended: <https://neon.tech>). Sign in with
   GitHub, create a project, copy the connection string. No payment details are
   needed for the free tier.
3. **Streamlit Community Cloud** (<https://share.streamlit.io>). Sign in with GitHub
   and allow it to read the repo.

## Step by step

### 1. Create the database
In Neon: *New project* → region *US East (Ohio)* or *US Central* → copy the
**connection string** (it starts with `postgresql://`). Tables are created
automatically on first use.

Optional, more secure: create a second, read-only role for the dashboard
(`GRANT SELECT ON ALL TABLES IN SCHEMA public TO dashboard_ro;`) and give that
URL to Streamlit. Note the Reviewer page needs write access; if you use a
read-only role, record review decisions with `python -m ndwatch review ...`
instead.

### 2. Give GitHub Actions the database URL
Repo → *Settings* → *Secrets and variables* → *Actions* → *New repository secret*:

- Name `DATABASE_URL`, value: the connection string.

Optional *Variables* (same page, *Variables* tab):

- `NDWATCH_EXTRA_ASSEMBLIES` = `69-2025` keeps the 2025 session loaded after the
  70th Assembly appears.

Then run it once by hand: *Actions* → *Monitor official sources* → *Run workflow*.
The first run loads the whole assembly (about 2–5 minutes). Bill text is
downloaded gradually, 400 documents per run, so full-text detection is complete
after about 10 hourly runs (the monitor keeps an hourly pace until this backlog is done).

### 3. Deploy the dashboard
share.streamlit.io → *Create app* → *Deploy a public app from GitHub* → repo
`MOREDataset/nd-lgbtq-legislative-watch`, branch `main`, file `streamlit_app.py`.
Under *Advanced settings* → *Secrets*, paste:

```toml
DATABASE_URL = "postgresql://...the same or a read-only connection string..."
NDWATCH_ADMIN_PASSWORD = "choose-a-long-password"   # enables the Reviewer page
```

Pick Python 3.12. Streamlit installs from `requirements.txt`.

### 4. Check it
- The top of every page shows when official sources were last checked.
- *About & Sources* lists each source with its last successful check.
- *Actions* → *Monitoring health check* runs every 6 hours and opens a GitHub
  issue (which emails you) if monitoring stops.

## Secrets
Secrets live only in GitHub Actions secrets and Streamlit secrets. `.env`,
`.streamlit/secrets.toml` and `data/` are git-ignored. Never paste a connection
string into an issue, commit, or chat.

## Moving off GitHub Actions later
The worker is one command: `python -m ndwatch monitor`. Any scheduler that can
run Python with `DATABASE_URL` set works (Render cron job, Fly.io machine,
a cloud function, a small VPS with cron). Nothing in the dashboard changes.

## Polling policy
The workflow wakes hourly; the program decides whether a full check is due:

| Period (detected from official session data) | Full check every |
|---|---|
| Session active (a current session with actions in the last 21 days) | 60 min |
| Prefiling (a session starts within 90 days) | 120 min |
| Off season | 12 h |

Change with `NDWATCH_POLL_*` variables. For 30-minute checks before hearings,
change the cron line to `"17,47 * * * *"` and set `NDWATCH_POLL_ACTIVE_MIN=30`.
