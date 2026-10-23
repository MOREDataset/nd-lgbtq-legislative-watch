"""Early-signal readers on REAL pages (tests/fixtures/signals_real, see PROVENANCE.json).

Pages were downloaded unmodified from ndlegis.gov, sos.nd.gov, translegislation.com and
aclu.org in October 2026.
"""

from __future__ import annotations

import dataclasses
import gzip
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from ndwatch.config import Settings
from ndwatch.db.schema import Event, Signal
from ndwatch.monitor import CycleReport
from ndwatch.signals import collect_signals
from ndwatch.sources.http import ReplayFetcher, url_to_filename
from ndwatch.sources.signals import (
    AGENCY_HEARINGS_RSS,
    SOS_MEASURES_URL,
    SOS_PETITIONS_URL,
    interim_index_url,
    parse_aclu,
    parse_agency_event,
    parse_agency_rss,
    parse_ballot_measures,
    parse_interim_committee,
    parse_interim_index,
    parse_tlt,
)

pytestmark = pytest.mark.historical

DIR = Path(__file__).parent / "fixtures" / "signals_real"
INTERIM = "https://ndlegis.gov/assembly/69-2025/committees/interim"


def page(url: str) -> str:
    return gzip.decompress((DIR / (url_to_filename(url) + ".gz")).read_bytes()).decode("utf-8", "replace")


def test_interim_index_lists_all_committees():
    committees = parse_interim_index(page(INTERIM), INTERIM)
    assert len(committees) == 39
    names = [n for n, _ in committees]
    assert "Human Services Committee" in names and "Judiciary Committee" in names
    assert all(u.startswith(INTERIM + "/") for _, u in committees)


def test_committee_page_studies_meetings_and_drafts():
    url = INTERIM + "/human-services-committee"
    c = parse_interim_committee(page(url), url)
    assert c.name == "Human Services Committee"
    assert len(c.studies) >= 20
    assert c.studies[0].reference == "1097 § 1" and c.studies[0].text.startswith("Study the accessibility")
    first = c.meetings[0]
    assert first.starts_at == datetime(2026, 9, 9, 14, 0)  # 9:00 am CDT
    assert first.agenda.endswith("27-5176-02000-meeting-agenda.pdf")
    assert [d.number for d in c.drafts] == ["27.0221.01000"]
    assert c.drafts[0].title.startswith("Relating to child care licensing")
    assert any(m.number == "27.9138.01000" for m in c.memos)
    assert not c.warnings


def test_agency_hearing_feed_and_event_page():
    items = parse_agency_rss(page(AGENCY_HEARINGS_RSS))
    assert len(items) == 50
    assert all(i.link.startswith("https://ndlegis.gov/events/") for i in items)
    url = "https://ndlegis.gov/events/2026/09/09/department-public-instruction"
    h = parse_agency_event(page(url), url)
    assert h.agency == "Department of Public Instruction"
    assert h.starts_at == datetime(2026, 9, 9, 14, 30)  # 9:30 AM CDT, from the page's calendar file
    assert h.notice_url.endswith("/rule-changes/notices/dpi090926notice.pdf")
    assert h.changes_url.endswith("/rule-changes/changes/dpi090926changes.pdf")


def test_ballot_measures_and_empty_petition_list():
    on_ballot = parse_ballot_measures(page(SOS_MEASURES_URL), SOS_MEASURES_URL)
    assert [m.name for m in on_ballot] == ["Constitutional Measure 1 – HCR 3003", "Constitutional Measure 2"]
    assert on_ballot[0].election == "2026 General Election"
    assert "Full Text of Measure" in on_ballot[0].documents
    # The petitions page says "None at this time." under each heading: no measures.
    assert parse_ballot_measures(page(SOS_PETITIONS_URL), SOS_PETITIONS_URL, "petition") == []


def test_tracker_lists():
    tlt25 = [b.number for b in parse_tlt(page("https://translegislation.com/bills/2025/ND"), "x")]
    assert tlt25 == ["HB1144", "HB1181", "HB1430", "HCR3013", "HR5001", "SB2244", "SB2392", "SCR4010", "SCR4021"]
    tlt23 = [b.number for b in parse_tlt(page("https://translegislation.com/bills/2023/ND"), "x")]
    assert len(tlt23) == 17 and "HB1254" in tlt23
    aclu = [b.number for b in parse_aclu(page("https://www.aclu.org/legislative-attacks-on-lgbtq-rights-2025?state=ND"), "x")]
    assert aclu == ["HB1144", "SB2244", "SB2392"]


def test_collect_signals_end_to_end_and_idempotent(factory):
    settings = dataclasses.replace(Settings(), request_interval=0, max_retries=0)
    fetcher = ReplayFetcher(DIR)
    with factory() as db:
        from ndwatch.db.schema import MonitorRun
        from ndwatch.timeutil import utcnow

        run = MonitorRun(started_at=utcnow(), status="running")
        db.add(run)
        db.commit()
        run_id = run.id
    report = CycleReport(run_id, "ok", "off_season")
    collect_signals(factory, fetcher, settings, report, ["69-2025"])
    assert not [e for e in report.errors if "Early signals" in e], report.errors
    with factory() as db:
        kinds = dict(db.execute(select(Signal.kind, func.count()).group_by(Signal.kind)).all())
        assert kinds["interim_study"] >= 60  # five committee pages are in the fixture set
        assert kinds["bill_draft"] == 1 and kinds["committee_meeting"] >= 20
        assert kinds["agency_rule"] == 50  # every hearing in the feed; 3 event pages are in the fixture set
        assert db.scalar(select(func.count()).select_from(Signal).where(Signal.kind == "agency_rule", Signal.event_at.is_not(None))) == 3
        assert kinds["ballot_measure"] == 2
        assert kinds["tracker"] == 9 + 3
        draft = db.get(Signal, "draft:27.0221.01000")
        assert draft.text_status == "ok" and "child care" in draft.text.lower()
        dpi = db.get(Signal, "rule:https://ndlegis.gov/events/2026/09/09/department-public-instruction")
        assert dpi.event_at == datetime(2026, 9, 9, 14, 30)
        assert all(s.backfill for s in db.scalars(select(Signal).where(Signal.kind != "tracker")))
        # A first load is history: nothing is announced as news.
        assert db.scalar(select(func.count()).select_from(Event).where(Event.backfill.is_(False))) == 0
        n_signals = db.scalar(select(func.count()).select_from(Signal))
    before = len(fetcher.requested)
    report2 = CycleReport(run_id, "ok", "off_season")
    collect_signals(factory, fetcher, settings, report2, ["69-2025"])
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Signal)) == n_signals
    second = fetcher.requested[before:]
    assert second.count(AGENCY_HEARINGS_RSS) == 1
    assert not any(u.startswith(interim_index_url("69-2025")) for u in second)  # daily sources wait a day
    assert not any("/events/2026/" in u for u in second)  # known hearings are not re-read
