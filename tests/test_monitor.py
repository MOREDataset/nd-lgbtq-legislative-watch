"""End-to-end monitoring cycles on SYNTHETIC data: change detection, idempotence, failures."""

from __future__ import annotations

import copy

from sqlalchemy import func, select

from ndwatch.db.schema import Bill, Event, Hearing, MonitorRun, Relevance, SourceFact, Summary, Testimony
from ndwatch.monitor import run_cycle
from ndwatch.sources.http import DictFetcher
from ndwatch.timeutil import utcnow
from tests.fixtures.synthetic import factory as syn
from tests.fixtures.synthetic.pdf import make_pdf

PDF_SCHOOL = make_pdf(["1 A BILL for an Act relating to transgender student accommodations;",
                       "2 a student may use a restroom designated for the student's sex."])
PDF_LICENSING = make_pdf(["1 A BILL for an Act relating to licensure of counselors.",
                          "2 A licensee may not provide conversion therapy to a minor. For purposes of",
                          "3 this section, conversion therapy means a practice that seeks to change an",
                          "4 individual's sexual orientation or gender identity."])
PDF_UNRELATED = make_pdf(["1 A BILL for an Act relating to snowmobile registration fees."])


def responses(bills_obj, **kw):
    r = syn.api_responses(bills_obj, **kw)
    r["https://ndlegis.gov/assembly/99-2097/regular/documents/97-0001-01000.pdf"] = PDF_SCHOOL
    r["https://ndlegis.gov/assembly/99-2097/regular/documents/97-0002-01000.pdf"] = PDF_LICENSING
    r["https://ndlegis.gov/assembly/99-2097/regular/documents/97-0003-01000.pdf"] = PDF_UNRELATED
    r["https://ndlegis.gov/assembly/99-2097/regular/bill-testimony/bt9001.html"] = syn.TESTIMONY_HTML.encode()
    r["https://ndlegis.gov/assembly/99-2097/regular/bill-testimony/bt9002.html"] = b"<html><table></table></html>"
    return r


def events(db, kind=None):
    q = select(Event)
    if kind:
        q = q.where(Event.kind == kind)
    return db.scalars(q).all()


def base_bills():
    return [syn.bill_school(), syn.bill_licensing(), syn.bill_unrelated()]


def test_first_load_then_idempotent(factory, settings):
    r1 = run_cycle(factory, DictFetcher(responses(syn.bills(*base_bills()))), settings, force=True)
    assert r1.status == "ok", r1.errors
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Bill)) == 3
        assert all(e.backfill for e in events(db, "new_bill"))  # history is not "news"
        n_events = len(events(db))
    r2 = run_cycle(factory, DictFetcher(responses(syn.bills(*base_bills()))), settings, force=True)
    assert r2.status == "ok"
    with factory() as db:
        assert len(events(db)) == n_events  # nothing duplicated


def test_relevance_finds_generic_title_bill_from_text(factory, settings):
    run_cycle(factory, DictFetcher(responses(syn.bills(*base_bills()))), settings, force=True)
    with factory() as db:
        rel = {r.bill_uid: r for r in db.scalars(select(Relevance))}
    assert rel["209701:HB9001"].status == "relevant" and rel["209701:HB9001"].level == "direct"
    lic = rel["209701:HB9002"]
    assert lic.status == "relevant", lic.score
    assert any(e["where"] == "text" and "conversion therapy" in e["snippet"].lower() for e in lic.evidence)
    assert rel["209701:SB9003"].status == "not_relevant"


def test_new_action_new_version_hearing_changes(factory, settings):
    run_cycle(factory, DictFetcher(responses(syn.bills(*base_bills()))), settings, force=True)
    with factory() as db:
        db.add(Summary(bill_uid="209701:HB9001", lc_number="97.0001.01000", kind="human",
                       about="x", created_at=utcnow()))
        db.commit()

    b = syn.bill_school()
    b["actions"].append({"id": 1002, "description": "Committee Hearing 10:00", "date": "2097-01-20T10:00:00",
                         "category": "Committee", "chamber": "House", "bill_version": None, "roll_call": {}})
    b["hearings"] = [syn.hearing(5001, "2097-01-20T10:00:00")]
    run_cycle(factory, DictFetcher(responses(syn.bills(b, syn.bill_licensing(), syn.bill_unrelated()))), settings, force=True)
    with factory() as db:
        sched = events(db, "hearing_scheduled")
        assert len(sched) == 1 and not sched[0].backfill
        assert "Jan 20, 2097, 10:00 AM CT" in sched[0].title

    # Reschedule + amendment + new version
    b2 = copy.deepcopy(b)
    b2["hearings"] = [syn.hearing(5001, "2097-01-21T14:30:00", room="327E")]
    b2["actions"].append({"id": 1003, "description": "Reported back amended, do pass, amendment placed on calendar 12 0 1",
                          "date": "2097-01-22T23:59:59", "category": "Committee", "chamber": "House",
                          "bill_version": "97.0001.01001", "roll_call": {}})
    b2["versions"].append({"lc_number": "97.0001.01001", "description": "Prepared by the Legislative Council staff for House Education - amendment",
                           "document_url": "https://ndlegis.gov/assembly/99-2097/regular/documents/97-0001-01001.pdf"})
    run_cycle(factory, DictFetcher(responses(syn.bills(b2, syn.bill_licensing(), syn.bill_unrelated()))), settings, force=True)
    with factory() as db:
        moved = events(db, "hearing_changed")
        assert len(moved) == 1 and "327E" in moved[0].title and "Previously" in moved[0].detail
        assert len(events(db, "new_version")) == 1
        assert len(events(db, "committee_do_pass")) == 1
        assert db.scalars(select(Summary)).one().needs_review is True

    # Same data again: nothing new.
    with factory() as db:
        before = len(events(db))
    run_cycle(factory, DictFetcher(responses(syn.bills(b2, syn.bill_licensing(), syn.bill_unrelated()))), settings, force=True)
    with factory() as db:
        assert len(events(db)) == before

    # Hearing disappears from the official list.
    b3 = copy.deepcopy(b2)
    b3["hearings"] = []
    run_cycle(factory, DictFetcher(responses(syn.bills(b3, syn.bill_licensing(), syn.bill_unrelated()))), settings, force=True)
    with factory() as db:
        assert len(events(db, "hearing_removed")) == 1
        h = db.scalars(select(Hearing)).one()
        assert h.removed_at is not None  # kept, not deleted


def test_vote_and_law(factory, settings):
    run_cycle(factory, DictFetcher(responses(syn.bills(*base_bills()))), settings, force=True)
    b = syn.bill_school()
    b["actions"] += [
        {"id": 1010, "description": "Second reading, passed, yeas 60 nays 30", "date": "2097-02-07T23:59:59",
         "category": "Floor", "chamber": "House", "bill_version": "97.0001.01000",
         "roll_call": {"id": "209701H00010", "chamber": "House", "date": "2097-02-07T14:01:00",
                       "description": "Final Passage", "division": None, "passed": True,
                       "total_yeas": 60, "total_nays": 30, "total_absent": 4}},
        {"id": 1011, "description": "Received from House", "date": "2097-02-09T23:59:59", "category": "Senate",
         "chamber": "Senate", "bill_version": None, "roll_call": {}},
        {"id": 1012, "description": "Second reading, passed, yeas 30 nays 17", "date": "2097-03-20T23:59:59",
         "category": "Floor", "chamber": "Senate", "bill_version": None, "roll_call": {}},
        {"id": 1013, "description": "Sent to Governor", "date": "2097-03-25T23:59:59", "category": "Governor",
         "chamber": "House", "bill_version": None, "roll_call": {}},
        {"id": 1014, "description": "Signed by Governor 03/28", "date": "2097-03-28T23:59:59", "category": "Governor",
         "chamber": None, "bill_version": None, "roll_call": {}},
        {"id": 1015, "description": "Filed with Secretary Of State 03/29", "date": "2097-03-29T23:59:59",
         "category": "Filed", "chamber": None, "bill_version": None, "roll_call": {}},
    ]
    b["passed"] = True
    b["current_status"] = "Governor signed"
    run_cycle(factory, DictFetcher(responses(syn.bills(b, syn.bill_licensing(), syn.bill_unrelated()))), settings, force=True)
    with factory() as db:
        bill = db.get(Bill, "209701:HB9001")
        assert bill.outcome == "became_law"
        passed = events(db, "floor_passed")
        assert any("60 yes, 30 no" in e.title and "House" in e.title for e in passed)
        assert len(events(db, "outcome_became_law")) == 1


def test_same_number_different_sessions_do_not_collide(factory, settings):
    special = syn.bill_school(session_id="209702", session_name="Special Session - Nov 2097",
                              summary="Relating to something else entirely.")
    data = syn.bills(syn.bill_school())
    data["bills"]["9001-special"] = special
    run_cycle(factory, DictFetcher(responses(data)), settings, force=True)
    with factory() as db:
        uids = set(db.scalars(select(Bill.uid)))
    assert {"209701:HB9001", "209702:HB9001"} <= uids


def test_source_failure_keeps_stored_data(factory, settings):
    run_cycle(factory, DictFetcher(responses(syn.bills(*base_bills()))), settings, force=True)
    r = responses(syn.bills(*base_bills()))
    r["https://ndlegis.gov/api/assembly/99-2097/data/bills.json"] = 503
    report = run_cycle(factory, DictFetcher(r), settings, force=True)
    assert report.status == "partial"
    assert any("bills" in e for e in report.errors)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Bill)) == 3


def test_everything_down_marks_failed_without_data(factory, settings):
    report = run_cycle(factory, DictFetcher({}), settings, force=True)
    assert report.status == "failed"
    with factory() as db:
        assert db.scalars(select(MonitorRun)).one().status == "failed"


def test_new_assembly_without_bills_is_not_an_error(factory, settings):
    r = responses(syn.bills(*base_bills()), assemblies_obj=syn.assemblies(include_next=True))
    r["https://ndlegis.gov/api/assembly/100-2099/data/sessions.json"] = syn.to_bytes(
        {"assembly": 100, "biennium_start": 2099, "sessions": []})
    r["https://ndlegis.gov/api/assembly/100-2099/data/members.json"] = syn.to_bytes(
        {"assembly": 100, "members": []})
    # bills.json for the new assembly is not published yet -> 404
    report = run_cycle(factory, DictFetcher(r), settings, force=True)
    assert not any("100-2099 bills" in e for e in report.errors), report.errors
    assert any("no bills published yet" in n for n in report.notes)
    # The assembly with the current session is still monitored.
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Bill)) == 3


def test_policy_skips_when_not_due(factory, settings):
    run_cycle(factory, DictFetcher(responses(syn.bills(*base_bills()))), settings, force=True)
    report = run_cycle(factory, DictFetcher(responses(syn.bills(*base_bills()))), settings)
    assert report.status == "skipped"


def test_testimony_and_rules_collected(factory, settings):
    run_cycle(factory, DictFetcher(responses(syn.bills(*base_bills()))), settings, force=True)
    with factory() as db:
        t = db.scalars(select(Testimony).order_by(Testimony.document_number)).all()
        assert [x.position for x in t] == ["In Opposition", "In Favor"]
        rule = db.get(SourceFact, "testimony_deadline_rule")
        assert "one hour before" in rule.value
        assert db.get(SourceFact, "how_to_submit_testimony_url").value.endswith("how_to_submit_bill_testimony.pdf")
