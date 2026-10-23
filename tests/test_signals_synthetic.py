"""Early signals on SYNTHETIC pages (fictional 99th Assembly, 2097): scoring, news events,
removed items and tracker suggestions."""

from __future__ import annotations

import dataclasses
import json
from datetime import timedelta

from sqlalchemy import select

from ndwatch.config import Settings
from ndwatch.db.schema import Event, MonitorRun, ReviewDecision, Signal, SourceCheck
from ndwatch.monitor import CycleReport, run_cycle
from ndwatch.signals import collect_signals, tracker_suggestions
from ndwatch.sources.http import DictFetcher
from ndwatch.sources.signals import AGENCY_HEARINGS_RSS, interim_index_url
from ndwatch.timeutil import utcnow
from tests.fixtures.synthetic import factory as syn
from tests.fixtures.synthetic.pdf import make_pdf

YEAR = "99-2097"
INDEX = interim_index_url(YEAR)
CMTE = f"{INDEX}/example-committee"
DRAFT = "https://ndlegis.gov/sites/default/files/pdf/committees/99-2097/99.0001.01000.pdf"


def committee_page(studies: list[str]) -> bytes:
    paras = "".join(f'<p>(<a href="https://ndlegis.gov/x.pdf">9{i} § 1</a>) {t}</p>' for i, t in enumerate(studies))
    return f"""<html><body><h1>Example Committee</h1><main>
<button class="ac-trigger" aria-label="March 3, 2098 - 9:00 am to 3:00 pm CST">March 3, 2098</button>
<div><a href="/assembly/99-2097/interim/99-5001-02000-meeting-agenda.pdf">Agenda</a>
<div class="bill-draft-item"><a href="{DRAFT}">99.0001.01000 - Relating to vital records.</a></div></div>
<div class="field--name-field-cmte-studies-assignments"><div class="field__item"><p><strong>Studies</strong></p>{paras}</div></div>
</main></body></html>""".encode()


INDEX_PAGE = f'<html><main><a href="{CMTE}">Example Committee</a></main></html>'.encode()
DRAFT_PDF = make_pdf(["1 A BILL for an Act relating to vital records. A birth certificate must list",
                      "2 the sex of the child and may not be amended to reflect gender identity."])
EMPTY_RSS = b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'


def tlt_page(numbers: list[str]) -> bytes:
    data = {"props": {"pageProps": {"bills": [{"bill_number": n, "title": "x"} for n in numbers]}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'.encode()


def run(factory, fetcher):
    settings = dataclasses.replace(Settings(), request_interval=0, max_retries=0)
    with factory() as db:
        r = MonitorRun(started_at=utcnow(), status="running")
        db.add(r)
        db.commit()
        rid = r.id
    report = CycleReport(rid, "ok", "off_season")
    collect_signals(factory, fetcher, settings, report, [YEAR])
    return report


def age_checks(factory, days=2):
    with factory() as db:
        for c in db.scalars(select(SourceCheck)):
            c.checked_at -= timedelta(days=days)
        db.commit()


def test_first_load_is_quiet_then_new_study_is_news(factory):
    responses = {INDEX: INDEX_PAGE, CMTE: committee_page(["Study snowmobile trail funding and grooming schedules."]),
                 DRAFT: DRAFT_PDF, AGENCY_HEARINGS_RSS: EMPTY_RSS}
    report = run(factory, DictFetcher(responses))
    assert not [e for e in report.errors if "Early signals" in e], report.errors
    with factory() as db:
        draft = db.get(Signal, "draft:99.0001.01000")
        assert draft.status == "relevant" and "identity_documents" in draft.topics
        assert draft.backfill
        assert db.scalars(select(Event).where(Event.backfill.is_(False))).all() == []

    # A day later the committee is assigned a new study on a matching topic.
    age_checks(factory)
    responses[CMTE] = committee_page([
        "Study snowmobile trail funding and grooming schedules.",
        "Study policies on gender identity and pronoun use in state agencies.",
    ])
    run(factory, DictFetcher(responses))
    with factory() as db:
        news = db.scalars(select(Event).where(Event.backfill.is_(False))).all()
        assert [e.kind for e in news] == ["signal_interim_study"]
        assert "Example Committee" in news[0].title and "gender identity" in news[0].title
        assert news[0].source_url == "https://ndlegis.gov/x.pdf"

    # Running again changes nothing.
    age_checks(factory)
    run(factory, DictFetcher(responses))
    with factory() as db:
        assert len(db.scalars(select(Event).where(Event.backfill.is_(False))).all()) == 1


def test_items_that_disappear_are_kept_and_marked(factory):
    responses = {INDEX: INDEX_PAGE, CMTE: committee_page(["Study policies on gender identity in schools."]),
                 DRAFT: DRAFT_PDF, AGENCY_HEARINGS_RSS: EMPTY_RSS}
    run(factory, DictFetcher(responses))
    age_checks(factory)
    responses[CMTE] = committee_page([])
    run(factory, DictFetcher(responses))
    with factory() as db:
        studies = db.scalars(select(Signal).where(Signal.kind == "interim_study")).all()
        assert len(studies) == 1 and studies[0].removed_at is not None


def test_tracker_names_a_bill_we_did_not_list(factory, settings):
    bills = syn.bills(syn.bill_school(), syn.bill_unrelated())  # HB 9001 relevant, SB 9003 not
    run_cycle(factory, DictFetcher(syn.api_responses(bills)), settings, force=True)
    responses = {AGENCY_HEARINGS_RSS: EMPTY_RSS,
                 "https://translegislation.com/bills/2097/ND": tlt_page(["HB9001", "SB9003", "SB9999"])}
    run(factory, DictFetcher(responses))
    with factory() as db:
        sugg = tracker_suggestions(db)
        assert [s["name"] for s in sugg] == ["SB 9003"]  # HB 9001 is already listed; SB 9999 does not exist
        assert sugg[0]["trackers"] == ["Trans Legislation Tracker"]
        # Once a reviewer decides, the suggestion goes away.
        db.add(ReviewDecision(bill_uid=sugg[0]["uid"], decision="exclude", reason="Snowmobile fees only",
                              created_at=utcnow()))
        db.commit()
        assert tracker_suggestions(db) == []
        # Tracker items never create public events.
        assert db.scalars(select(Event).where(Event.kind.like("signal_%"))).all() == []


def test_unreachable_sources_do_not_fail_the_run(factory):
    report = run(factory, DictFetcher({}))
    assert not [e for e in report.errors if e.startswith("Early signals (")], report.errors
    assert any("Agency rule hearings feed" in e for e in report.errors)
