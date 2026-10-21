"""Plain-English descriptions of official actions, used in the activity feed.

The official wording is always kept alongside (in `detail`), so the
plain-English line can be checked against the source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LOW, MEDIUM, HIGH = 1, 2, 3


@dataclass
class ActionEvent:
    kind: str
    importance: int
    title: str


_VOTES = re.compile(r"yeas?\s*(\d+)\s*,?\s*nays?\s*(\d+)", re.I)
_COMMITTEE = re.compile(r"referred (?:to )?(?:the )?(.+?)(?: committee)?$", re.I)


def vote_counts(description: str) -> tuple[int, int] | None:
    m = _VOTES.search(description or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def describe_action(
    bill: str,
    description: str,
    chamber: str | None,
    yeas: int | None = None,
    nays: int | None = None,
) -> ActionEvent:
    d = (description or "").strip()
    low = d.lower()
    where = f"the {chamber}" if chamber else "the Legislature"
    where_cap = where[0].upper() + where[1:]
    counts = (yeas, nays) if yeas is not None and nays is not None else vote_counts(d)
    tally = f" ({counts[0]} yes, {counts[1]} no)" if counts else ""

    if "signed by governor" in low or "governor signed" in low:
        return ActionEvent("signed", HIGH, f"The Governor signed {bill}.")
    if "without" in low and "signature" in low:
        return ActionEvent("law_without_signature", HIGH, f"{bill} became law without the Governor's signature.")
    if "veto overridden" in low or "notwithstanding" in low:
        return ActionEvent("veto_override", HIGH, f"{where_cap} overrode the Governor's veto of {bill}.")
    if "veto sustained" in low:
        return ActionEvent("veto_sustained", HIGH, f"The veto of {bill} stands; {where} did not override it.")
    if "vetoed" in low:
        return ActionEvent("vetoed", HIGH, f"The Governor vetoed {bill}.")
    if "sent to governor" in low or re.search(r"\bto governor\b", low):
        return ActionEvent("to_governor", HIGH, f"{bill} was sent to the Governor for a decision.")
    if "filed with secretary of state" in low:
        return ActionEvent("filed", MEDIUM, f"{bill} was filed with the Secretary of State (the final official step).")
    if "withdrawn" in low:
        return ActionEvent("withdrawn", HIGH, f"{bill} was withdrawn.")
    if "second reading" in low and "failed" in low:
        return ActionEvent("floor_failed", HIGH, f"{where_cap} voted on {bill}: it did not pass{tally}.")
    if "second reading" in low and "passed" in low:
        amended = " with changes (amended)" if "amended" in low else ""
        return ActionEvent("floor_passed", HIGH, f"{where_cap} voted to pass {bill}{amended}{tally}.")
    if "refused to concur" in low:
        return ActionEvent(
            "refused_concur", MEDIUM, f"{where_cap} did not agree to the other chamber's changes to {bill}."
        )
    if "conference committee" in low and ("appointed" in low or "request" in low):
        return ActionEvent(
            "conference", MEDIUM,
            f"A conference committee (legislators from both chambers) will work out differences on {bill}.",
        )
    if "conference committee report" in low and "adopted" in low:
        return ActionEvent("conference_adopted", HIGH, f"{where_cap} accepted the conference committee's version of {bill}.")
    if re.search(r"\bconcurred\b", low):
        return ActionEvent("concurred", HIGH, f"{where_cap} agreed to the other chamber's changes to {bill}.")
    if re.search(r"do not pass", low):
        return ActionEvent(
            "committee_do_not_pass", MEDIUM,
            f"A {chamber or ''} committee recommended that {bill} not pass. The full {chamber or 'chamber'} still votes.".replace("A  ", "A "),
        )
    if re.search(r"do pass", low):
        changes = " with changes" if "amend" in low else ""
        return ActionEvent(
            "committee_do_pass", MEDIUM,
            f"A {chamber or ''} committee recommended passing {bill}{changes}. The full {chamber or 'chamber'} votes next.".replace("A  ", "A "),
        )
    if re.search(r"\bamendment(s)? adopted\b|\bamendment placed\b", low):
        return ActionEvent("amended", MEDIUM, f"Changes (amendments) to {bill} were adopted.")
    if "introduced" in low or "first reading" in low:
        m = re.search(r"referred (?:to )?(.+)", d, re.I)
        to = f" and sent to the {m.group(1).rstrip('.')} for review" if m else ""
        return ActionEvent("introduced", MEDIUM, f"{bill} was introduced in {where}{to}.")
    if "received from" in low:
        return ActionEvent("crossed_over", MEDIUM, f"{bill} moved to {where} for consideration.")
    if "rereferred" in low or "referred" in low:
        m = _COMMITTEE.search(d)
        to = m.group(1) if m else "a committee"
        return ActionEvent("referred", LOW, f"{bill} was sent to {to} for review.")
    if "committee hearing" in low:
        return ActionEvent("hearing_held", LOW, f"A committee hearing on {bill} was recorded in the official actions.")
    return ActionEvent("action", LOW, f"Official action on {bill}: “{d}”")
