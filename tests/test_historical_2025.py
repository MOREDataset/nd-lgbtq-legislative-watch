"""Validation against REAL records from the 2025 North Dakota regular session.

The files in tests/fixtures/historical are unmodified official responses (or
subsets of them, with other bills removed). See PROVENANCE.json for source URLs
and retrieval times. These are historical bills; nothing here is live data.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import func, select

from ndwatch.config import Settings
from ndwatch.db.schema import (
    Bill,
    Event,
    Hearing,
    MemberVote,
    Relevance,
    RollCall,
    SourceFact,
    Testimony,
)
from ndwatch.monitor import run_cycle
from ndwatch.sources.http import ReplayFetcher
from ndwatch.timeutil import fmt_date
from ndwatch.ui import data as D

pytestmark = pytest.mark.historical
FIXTURES = Path(__file__).parent / "fixtures" / "historical"


@pytest.fixture(scope="module")
def loaded(tmp_path_factory):
    from ndwatch.db.session import init_db, make_engine, session_factory

    db_path = tmp_path_factory.mktemp("hist") / "hist.db"
    engine = make_engine(f"sqlite:///{db_path}")
    init_db(engine)
    factory = session_factory(engine)
    settings = dataclasses.replace(Settings(), request_interval=0, max_retries=0, extra_assemblies=("69-2025",),
                                   signals_enabled=False)
    report = run_cycle(factory, ReplayFetcher(FIXTURES), settings, force=True, only_assemblies=["69-2025"])
    return factory, settings, report


def test_cycle_completes(loaded):
    _, _, report = loaded
    # Only bill-text PDFs we did not archive may be missing; no source-level errors.
    assert report.status == "ok", report.errors


def test_hb1144_facts(loaded):
    factory, _, _ = loaded
    with factory() as db:
        b = db.get(Bill, "202501:HB1144")
        assert b.summary.startswith("Relating to transgender student accommodations and restroom use")
        assert b.outcome == "became_law"
        assert b.current_status == "Governor signed"
        primary = [s for s in b.sponsors if s.primary]
        assert primary and primary[0].chamber == "House"
        # House floor vote, verified against the official overview page: 73 yeas, 18 nays.
        rc = db.get(RollCall, "202501H00291")
        assert (rc.total_yeas, rc.total_nays, rc.chamber) == (73, 18, "House")
        votes = Counter(v.vote for v in db.scalars(select(MemberVote).where(MemberVote.roll_call_id == rc.id)))
        assert votes["Yea"] == 73 and votes["Nay"] == 18
        # First House hearing: Jan 27, 2025, 3:15 PM Central (Pioneer Room).
        first = min((h for h in b.hearings if h.type == "Bill Hearing"), key=lambda h: h.starts_at)
        assert fmt_date(first.starts_at) == "Mon, Jan 27, 2025, 3:15 PM CT"
        assert first.room == "Pioneer"


def test_hb1144_path_shows_amendments_and_conference(loaded):
    factory, _, _ = loaded
    with factory() as db:
        d = D.bill_detail(db, "202501:HB1144")
    p = d["path"]
    assert p.amended and p.conference
    assert p.outcome == "became_law"
    assert [s.state for s in p.steps] == ["done"] * len(p.steps)


def test_hb1144_testimony_matches_official_page(loaded):
    factory, _, _ = loaded
    with factory() as db:
        rows = db.scalars(select(Testimony).where(Testimony.bill_uid == "202501:HB1144")).all()
    assert len(rows) == 112
    assert Counter(r.position for r in rows) == {"In Opposition": 80, "In Favor": 29, "Neutral": 3}
    assert all(r.document_url.startswith("https://ndlegis.gov/assembly/69-2025/testimony/") for r in rows)


def test_hb1217_hiv_bill_found_and_became_law(loaded):
    factory, _, _ = loaded
    with factory() as db:
        b = db.get(Bill, "202501:HB1217")
        r = db.get(Relevance, "202501:HB1217")
    assert b.outcome == "became_law"
    assert r.status == "relevant" and "hiv_public_health" in r.topics


def test_hb1430_found_from_bill_text_not_title(loaded):
    """HB 1430's title is about 'regulation of social workers'; only the text shows relevance."""
    factory, _, _ = loaded
    with factory() as db:
        b = db.get(Bill, "202501:HB1430")
        r = db.get(Relevance, "202501:HB1430")
    assert "social workers" in b.title and "gender" not in b.title.lower()
    assert r.status == "relevant"
    assert all(e["where"] == "text" for e in r.evidence)
    assert {"sogi", "sex_definitions"} <= set(r.topics)
    assert b.outcome == "failed"


def test_unrelated_bill_not_flagged(loaded):
    factory, _, _ = loaded
    with factory() as db:
        r = db.get(Relevance, "202501:HB1001")
    assert r.status == "not_relevant"


def test_veto_recorded(loaded):
    factory, _, _ = loaded
    with factory() as db:
        assert db.get(Bill, "202501:SB2307").outcome == "vetoed"


def test_historical_bills_are_not_live(loaded):
    factory, _, _ = loaded
    with factory() as db:
        cards = D.bill_cards(db)
    assert cards and not any(c["live"] for c in cards)


def test_testimony_rule_read_from_official_page(loaded):
    factory, _, _ = loaded
    with factory() as db:
        f = db.get(SourceFact, "testimony_deadline_rule")
    assert f.value == "The deadline to submit testimony for public hearings is one hour before the start of the committee hearing."


def test_rerun_creates_no_duplicates(loaded):
    factory, settings, _ = loaded
    with factory() as db:
        before = db.scalar(select(func.count()).select_from(Event))
        hearings = db.scalar(select(func.count()).select_from(Hearing))
    run_cycle(factory, ReplayFetcher(FIXTURES), settings, force=True, only_assemblies=["69-2025"])
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Event)) == before
        assert db.scalar(select(func.count()).select_from(Hearing)) == hearings
