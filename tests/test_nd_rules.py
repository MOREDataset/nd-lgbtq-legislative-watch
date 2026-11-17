"""North Dakota-specific process rules, on SYNTHETIC action sequences (wording copied from real 2025 actions)."""

from dataclasses import dataclass
from datetime import datetime

from ndwatch.explain import effective_date_note, explain_action
from ndwatch.process import build_path, is_constitutional_amendment, outcome_label


@dataclass
class A:
    description: str
    date: datetime
    chamber: str | None
    category: str | None = None


def d(day):
    return datetime(2097, 3, day)


GOVERNOR_SEQ = [
    A("Introduced, first reading, referred Judiciary Committee", d(1), "Senate"),
    A("Second reading, passed, yeas 40 nays 7", d(2), "Senate"),
    A("Received from Senate", d(3), "House"),
    A("Second reading, passed, yeas 70 nays 20", d(4), "House"),
    A("Sent to Governor", d(5), "Senate"),
    A("Vetoed by Governor 03/06", d(6), "Senate"),
    A("Consideration of Governor's veto", d(7), "Senate"),
]


def test_override_needs_both_chambers():
    one = GOVERNOR_SEQ + [A("Passed over veto, yeas 45 nays 2", d(7), "Senate")]
    p = build_path("SB 9200", "Senate", one)
    assert p.outcome == "vetoed"

    both = one + [
        A("Consideration of Governor's veto", d(8), "House"),
        A("Passed over veto, yeas 80 nays 12", d(8), "House"),
        A("Filed with Secretary Of State 03/10", d(10), None),
    ]
    p = build_path("SB 9200", "Senate", both)
    assert p.outcome == "became_law"
    assert {s.key: s.note for s in p.steps}["governor"] == "Veto overridden"


def test_override_sustained_in_second_chamber():
    seq = GOVERNOR_SEQ + [
        A("Passed over veto, yeas 45 nays 2", d(7), "Senate"),
        A("Consideration of Governor's veto", d(8), "House"),
        A("Veto sustained, yeas 15 nays 78", d(8), "House"),
    ]
    assert build_path("SB 9201", "Senate", seq).outcome == "vetoed"


def test_item_veto_is_law_with_a_note():
    seq = GOVERNOR_SEQ[:5] + [A("Signed by Governor, but item veto 03/06", d(6), "Senate")]
    p = build_path("SB 9202", "Senate", seq)
    assert p.outcome == "became_law" and p.item_veto
    assert any("item veto" in n for n in p.notes)


def test_constitutional_amendment_goes_to_voters():
    title = ("A concurrent resolution to amend and reenact section 9 of article III of the Constitution of "
             "North Dakota, relating to initiated measures.")
    assert is_constitutional_amendment("HCR 9300", title)
    assert not is_constitutional_amendment("HB 9300", title)
    assert not is_constitutional_amendment(
        "SCR 9301", "A concurrent resolution calling for a convention to amend the United States Constitution.")
    seq = [
        A("Introduced, first reading, referred Judiciary Committee", d(1), "House"),
        A("Second reading, adopted yeas 70 nays 20", d(2), "House"),
        A("Received from House", d(3), "Senate"),
        A("Second reading, adopted yeas 30 nays 17", d(4), "Senate"),
        A("Filed with Secretary Of State 03/05", d(5), None),
    ]
    p = build_path("HCR 9300", "House", seq, title=title)
    assert p.outcome == "adopted"
    assert "voters" in p.stage_label
    final = next(s for s in p.steps if s.key == "final")
    assert final.state == "current"
    assert "voters" in outcome_label("adopted", "HCR 9300", title)
    assert outcome_label("adopted", "HCR 9301", "A concurrent resolution urging Congress.") == "Adopted"


def test_emergency_clause_recorded():
    seq = [
        A("Introduced, first reading, (emergency), referred Appropriations Committee", d(1), "House"),
        A("Second reading, passed, yeas 69 nays 21, Emergency clause carried", d(2), "House"),
    ]
    assert build_path("HB 9400", "House", seq).emergency_clause is True
    seq.append(A("Emergency clause failed", d(3), "Senate"))
    assert build_path("HB 9400", "House", seq).emergency_clause is False


def test_effective_date_note():
    assert "August 1" in effective_date_note("AN ACT to amend and reenact section 1-01-01.", "2097 Regular Session", None)
    assert "filed" in effective_date_note("...; and to declare an emergency.", "2097 Regular Session", True)
    note = effective_date_note("...; and to declare an emergency.", "2097 Regular Session", False)
    assert "does not take effect early" in note and "August 1" in note
    assert "August 1" not in effective_date_note("AN ACT ...", "2097 Special Session", None)
    assert "own effective" in effective_date_note("...; to provide an effective date.", "2097 Regular Session", None)


def test_plain_action_wording():
    assert explain_action("Reported back amended, do pass, amendment placed on calendar 23 0 0", "House") == (
        "The committee recommended that the House pass the bill with changes to its wording "
        "(committee vote on this recommendation: 23 yes, 0 no, 0 absent). This is a recommendation; "
        "the full House still votes.")
    assert explain_action("Second reading, failed to pass, yeas 20 nays 72", "House") == "The full House voted it down, 20 to 72."
    assert "majority of all elected members" in explain_action(
        "Second reading, failed, lacks constitutional majority yeas 43 nays 42", "House")
    assert explain_action("Refused to concur", "Senate").startswith("The Senate did not agree")
    assert "both chambers" in explain_action("Passed over veto, yeas 45 nays 2", "Senate")
    assert explain_action("Something the clerk has never written before", "House") is None
    assert explain_action("", None) is None


def test_resolution_votes_and_other_actions_are_described():
    """Wording copied from real 2025 actions; these used to fall through to a hidden generic line."""
    from ndwatch.events import HIGH, MEDIUM, describe_action

    ev = describe_action("HCR 3013", "Second reading, adopted yeas 52 nays 40", "House")
    assert ev.importance == HIGH and ev.title == "The House voted to adopt HCR 3013 (52 yes, 40 no)."
    ev = describe_action("HCR 3013", "Second reading, failed to adopt", "Senate")
    assert ev.importance == HIGH and "not adopted" in ev.title
    ev = describe_action("SB 2261", "Passed over veto, yeas 45 nays 2", "Senate")
    assert ev.importance == HIGH and "both chambers" in ev.title
    assert describe_action("X", "Reported back without recommendation 6 1 0", "Senate").importance == MEDIUM
    assert describe_action("X", "Conference committee report rejected", "House").importance == MEDIUM
    assert describe_action("X", "Emergency clause failed", "Senate").importance == MEDIUM


def test_all_divisions_lost_means_failed():
    """REAL pattern (SB 2384, 2025): divided on the House floor and both parts lost."""
    seq = [
        A("Introduced, first reading, referred Judiciary Committee", d(1), "Senate"),
        A("Second reading, passed, yeas 24 nays 23", d(2), "Senate"),
        A("Received from Senate", d(3), "House"),
        A("Reported back, do not pass, placed on calendar 8 5 1", d(4), "House"),
        A("Division of bill", d(5), "House"),
        A("Division A lost", d(5), "House"),
        A("Division B lost", d(5), "House"),
    ]
    assert build_path("SB 2384", "Senate", seq).outcome == "failed"
    seq[-1] = A("Division B passed", d(5), "House")
    assert build_path("SB 2384", "Senate", seq).outcome is None


def test_resolution_about_line_uses_title():
    from ndwatch.explain import about_line

    t = "A concurrent resolution urging the United States Supreme Court to restore the definition of marriage."
    assert about_line(None, t) == "This is a " + t[2:]
    assert about_line("Relating to schools.", "AN ACT ...") == "This bill deals with schools."
