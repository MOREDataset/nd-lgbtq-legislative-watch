"""Legislative path building on SYNTHETIC action sequences."""

from dataclasses import dataclass
from datetime import datetime

from ndwatch.process import build_path


@dataclass
class A:
    description: str
    date: datetime
    chamber: str | None
    category: str | None = None


def d(day):
    return datetime(2097, 1, 1) .replace(day=day)


def states(path):
    return {s.key: s.state for s in path.steps}


def test_senate_bill_in_house_committee():
    p = build_path("SB 9100", "Senate", [
        A("Introduced, first reading, referred Judiciary Committee", d(5), "Senate"),
        A("Reported back, do pass, place on calendar 6 0 1", d(10), "Senate"),
        A("Second reading, passed, yeas 40 nays 7", d(12), "Senate"),
        A("Received from Senate", d(14), "House"),
        A("Introduced, first reading, referred Judiciary Committee", d(15), "House"),
    ])
    s = states(p)
    assert p.steps[0].label == "Introduced in the Senate"
    assert s["floor_1"] == "done"
    assert s["committee_2"] == "current"
    assert s["governor"] == "upcoming"
    assert p.outcome is None


def test_failed_in_first_chamber():
    p = build_path("HB 9101", "House", [
        A("Introduced, first reading, referred Education Committee", d(3), "House"),
        A("Reported back, do not pass, place on calendar 9 4 0", d(9), "House"),
        A("Second reading, failed to pass, yeas 20 nays 72", d(11), "House"),
    ])
    s = states(p)
    assert p.outcome == "failed"
    assert s["floor_1"] == "failed"
    assert s["committee_2"] == "skipped" and s["governor"] == "skipped"
    assert s["final"] == "failed"


def test_amendment_vote_failure_is_not_bill_failure():
    p = build_path("HB 9102", "House", [
        A("Introduced, first reading, referred Education Committee", d(3), "House"),
        A("Floor amendment failed", d(9), "House"),
    ])
    assert p.outcome is None


def test_veto():
    p = build_path("HB 9103", "House", [
        A("Introduced, first reading", d(1), "House"),
        A("Second reading, passed, yeas 60 nays 30", d(5), "House"),
        A("Received from House", d(6), "Senate"),
        A("Second reading, passed, yeas 30 nays 17", d(20), "Senate"),
        A("Sent to Governor", d(22), "House"),
        A("Vetoed by Governor", d(25), None),
    ])
    assert p.outcome == "vetoed"
    assert states(p)["governor"] == "failed"


def test_veto_overridden_becomes_law():
    p = build_path("HB 9104", "House", [
        A("Introduced, first reading", d(1), "House"),
        A("Second reading, passed, yeas 80 nays 10", d(5), "House"),
        A("Received from House", d(6), "Senate"),
        A("Second reading, passed, yeas 40 nays 5", d(20), "Senate"),
        A("Vetoed by Governor", d(25), None),
        A("Veto overridden, yeas 80 nays 10", d(27), "House"),
    ])
    assert p.outcome == "became_law"


def test_conference_and_amendments_flagged():
    p = build_path("HB 9105", "House", [
        A("Introduced, first reading", d(1), "House"),
        A("Second reading, passed, yeas 73 nays 18", d(5), "House"),
        A("Received from House", d(6), "Senate"),
        A("Second reading, passed as amended, yeas 40 nays 7", d(20), "Senate"),
        A("House refused to concur", d(21), "House"),
        A("Conference committee appointed", d(22), "House"),
    ])
    assert p.amended and p.conference
    assert p.outcome is None
    assert states(p)["governor"] == "current"


def test_single_chamber_resolution():
    p = build_path("HR 9106", "House", [
        A("Introduced, first reading", d(1), "House"),
        A("Second reading, adopted", d(5), "House"),
    ])
    assert [s.key for s in p.steps] == ["introduced", "committee_1", "floor_1", "final"]
    assert p.outcome == "adopted"


def test_no_actions_yet():
    p = build_path("SB 9107", None, [])
    assert p.outcome is None
    assert states(p)["introduced"] == "current"
