"""Turn the official action history into a legislative path a non-expert can read.

This module never invents steps. Each step is marked done only when an official
action supports it, and it points to that action. Bills can start in either
chamber, be amended, go to conference, fail, or be vetoed, and resolutions
follow different paths, so the path is built from the actions, not assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class ActionLike(Protocol):
    description: str
    date: datetime | None
    chamber: str | None
    category: str | None


# Step states
DONE, CURRENT, UPCOMING, FAILED, SKIPPED = "done", "current", "upcoming", "failed", "skipped"

# Final outcomes
OUTCOME_LAW = "became_law"
OUTCOME_VETOED = "vetoed"
OUTCOME_FAILED = "failed"
OUTCOME_ADOPTED = "adopted"  # resolutions
OUTCOME_WITHDRAWN = "withdrawn"
OUTCOME_PENDING_GOVERNOR = "awaiting_governor"

OUTCOME_LABELS = {
    OUTCOME_LAW: "Became law",
    OUTCOME_VETOED: "Vetoed by the Governor",
    OUTCOME_FAILED: "Did not pass",
    OUTCOME_ADOPTED: "Adopted",
    OUTCOME_WITHDRAWN: "Withdrawn",
    OUTCOME_PENDING_GOVERNOR: "Waiting for the Governor",
}


@dataclass
class Step:
    key: str
    label: str
    state: str = UPCOMING
    date: datetime | None = None
    note: str | None = None


@dataclass
class Path:
    steps: list[Step]
    outcome: str | None
    amended: bool = False
    conference: bool = False
    current_key: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def stage_label(self) -> str:
        if self.outcome:
            return OUTCOME_LABELS[self.outcome]
        for s in self.steps:
            if s.state == CURRENT:
                return s.label
        return "Introduced"


def bill_kind(name: str) -> str:
    """'HB 1144' -> 'HB'; 'SCR 4001' -> 'SCR'."""
    m = re.match(r"\s*([A-Za-z]+)", name or "")
    return m.group(1).upper() if m else ""


def origin_chamber(name: str, chamber: str | None) -> str:
    if chamber in ("House", "Senate"):
        return chamber
    return "Senate" if bill_kind(name).startswith("S") else "House"


def other(chamber: str) -> str:
    return "Senate" if chamber == "House" else "House"


_RX = {
    "intro": re.compile(r"\bintroduced\b|\bfirst reading\b|\bprefiled\b", re.I),
    "referred": re.compile(r"\breferred\b|\brereferred\b", re.I),
    "committee_report": re.compile(r"\bcommittee report\b|\breported back\b|\brecommends? do (not )?pass\b|\bdo (not )?pass\b", re.I),
    "amend": re.compile(r"\bamendment(s)? (adopted|placed)\b|\bpassed as amended\b|\bamended\b", re.I),
    "floor_pass": re.compile(r"\bsecond reading,? passed\b|\bpassed\b.*\byeas\b|\badopted\b", re.I),
    "floor_fail": re.compile(r"\bsecond reading,? failed\b|\bfailed to pass\b|\bfailed\b.*\byeas\b|\bnot adopted\b|\bfailed\b", re.I),
    "received": re.compile(r"\breceived from (house|senate)\b", re.I),
    "conference": re.compile(r"\bconference committee\b", re.I),
    "refuse_concur": re.compile(r"\brefused to concur\b", re.I),
    "concur": re.compile(r"\bconcurred\b|\bconcur\b", re.I),
    "to_governor": re.compile(r"\bsent to governor\b|\bto governor\b", re.I),
    "signed": re.compile(r"\bsigned by governor\b|\bgovernor signed\b", re.I),
    "veto": re.compile(r"\bvetoed\b|\bveto\b", re.I),
    "override_ok": re.compile(r"\bveto overridden\b|\boverride.*\bpassed\b|\bpassed notwithstanding\b", re.I),
    "override_fail": re.compile(r"\bveto sustained\b|\boverride.*\bfailed\b", re.I),
    "without_signature": re.compile(r"\bwithout (the )?(governor'?s )?signature\b", re.I),
    "filed_sos": re.compile(r"\bfiled with secretary of state\b", re.I),
    "withdrawn": re.compile(r"\bwithdrawn\b", re.I),
}


def build_path(name: str, chamber: str | None, actions: list[ActionLike], passed_flag: bool | None = None) -> Path:
    kind = bill_kind(name)
    origin = origin_chamber(name, chamber)
    second = other(origin)
    single_chamber = kind in ("HR", "SR", "HMR", "SMR")
    resolution = "R" in kind[1:] if len(kind) > 1 else False
    needs_governor = not resolution  # bills go to the Governor; resolutions do not

    steps = [Step("introduced", f"Introduced in the {origin}")]
    steps.append(Step("committee_1", f"{origin} committee review"))
    steps.append(Step("floor_1", f"{origin} vote"))
    if not single_chamber:
        steps.append(Step("committee_2", f"{second} committee review"))
        steps.append(Step("floor_2", f"{second} vote"))
    if needs_governor:
        steps.append(Step("governor", "Governor"))
    steps.append(Step("final", "Final outcome"))
    by_key = {s.key: s for s in steps}

    path = Path(steps=steps, outcome=None)
    ordered = sorted(actions, key=lambda a: (a.date or datetime.min))

    def mark(key: str, state: str, when: datetime | None, note: str | None = None) -> None:
        s = by_key.get(key)
        if s is None:
            return
        s.state = state
        s.date = when or s.date
        if note:
            s.note = note

    for a in ordered:
        d = (a.description or "").strip()
        ch = a.chamber
        in_second = ch == second
        if _RX["withdrawn"].search(d):
            path.outcome = OUTCOME_WITHDRAWN
            continue
        if _RX["conference"].search(d):
            path.conference = True
        if _RX["amend"].search(d):
            path.amended = True

        if _RX["intro"].search(d) and not in_second:
            mark("introduced", DONE, a.date)
            if _RX["referred"].search(d):
                mark("committee_1", CURRENT, a.date)
            continue
        if (_RX["received"].search(d) or (_RX["intro"].search(d) and in_second)) and not single_chamber:
            mark("floor_1", DONE, by_key["floor_1"].date or a.date)
            mark("committee_2", CURRENT, a.date)
            continue
        if _RX["referred"].search(d) and not _RX["floor_pass"].search(d):
            mark("committee_2" if in_second else "committee_1", CURRENT, a.date)
            continue
        if _RX["committee_report"].search(d) and not _RX["floor_pass"].search(d):
            key = "committee_2" if in_second else "committee_1"
            mark(key, DONE, a.date, note=d)
            continue
        if _RX["signed"].search(d):
            mark("governor", DONE, a.date, note="Signed by the Governor")
            path.outcome = OUTCOME_LAW
            continue
        if _RX["without_signature"].search(d):
            mark("governor", DONE, a.date, note="Became law without the Governor's signature")
            path.outcome = OUTCOME_LAW
            continue
        if _RX["override_ok"].search(d):
            mark("governor", DONE, a.date, note="Veto overridden")
            path.outcome = OUTCOME_LAW
            continue
        if _RX["override_fail"].search(d):
            path.outcome = OUTCOME_VETOED
            continue
        if _RX["veto"].search(d):
            mark("governor", FAILED, a.date, note="Vetoed")
            path.outcome = OUTCOME_VETOED
            continue
        if _RX["to_governor"].search(d):
            mark("governor", CURRENT, a.date)
            continue
        if _RX["filed_sos"].search(d):
            if resolution and path.outcome is None:
                path.outcome = OUTCOME_ADOPTED
            continue
        # Votes on amendments or procedural motions are not a vote on the bill.
        if not re.search(r"\bsecond reading\b|\bfinal passage\b", d, re.I) and re.search(
            r"\bamendment\b|\bmotion\b|\breconsider", d, re.I
        ):
            continue
        is_floor = bool(re.search(r"\bsecond reading\b|\byeas\b|\bfinal passage\b|\badopted\b|\bnot adopted\b", d, re.I))
        if is_floor and _RX["floor_fail"].search(d) and not _RX["floor_pass"].search(d.replace("failed", "")):
            key = "floor_2" if in_second else "floor_1"
            mark(key, FAILED, a.date, note=d)
            path.outcome = OUTCOME_FAILED
            continue
        if is_floor and _RX["floor_pass"].search(d):
            key = "floor_2" if in_second else "floor_1"
            # A floor vote implies the committee stage finished.
            ckey = "committee_2" if in_second else "committee_1"
            if by_key.get(ckey) and by_key[ckey].state in (UPCOMING, CURRENT):
                mark(ckey, DONE, by_key[ckey].date)
            mark(key, DONE, a.date, note=d)
            # A reconsidered/passed bill is no longer failed.
            if path.outcome == OUTCOME_FAILED:
                path.outcome = None
            if key == "floor_1" and single_chamber and resolution:
                path.outcome = OUTCOME_ADOPTED
            continue

    # Fill in: anything before the furthest DONE step is done too (some
    # actions, like committee reports, are not always listed).
    last_done = max((i for i, s in enumerate(steps) if s.state in (DONE, FAILED)), default=-1)
    for i in range(last_done):
        if steps[i].state in (UPCOMING, CURRENT):
            steps[i].state = DONE

    if path.outcome in (OUTCOME_LAW, OUTCOME_ADOPTED):
        by_key["final"].state = DONE
        by_key["final"].note = OUTCOME_LABELS[path.outcome]
        for s in steps:
            if s.state in (UPCOMING, CURRENT):
                s.state = DONE if s.key != "final" else s.state
    elif path.outcome in (OUTCOME_FAILED, OUTCOME_VETOED, OUTCOME_WITHDRAWN):
        by_key["final"].state = FAILED
        by_key["final"].note = OUTCOME_LABELS[path.outcome]
        hit_fail = False
        for s in steps:
            if s.state == FAILED:
                hit_fail = True
                continue
            if hit_fail and s.key != "final" or s.state == CURRENT:
                s.state = SKIPPED
    else:
        # Exactly one current step: the first not-done step.
        if not any(s.state == CURRENT for s in steps):
            for s in steps:
                if s.state == UPCOMING:
                    s.state = CURRENT
                    break
        else:
            seen_current = False
            for s in steps:
                if s.state == CURRENT:
                    if seen_current:
                        s.state = UPCOMING
                    seen_current = True
        # A "current" step that comes after a later DONE is just upcoming noise.
        cur = [i for i, s in enumerate(steps) if s.state == CURRENT]
        if cur and cur[0] < last_done:
            steps[cur[0]].state = DONE

    # Cross-check with the API's own `passed` flag; we report mismatch rather than guess.
    if passed_flag is True and path.outcome in (OUTCOME_FAILED, OUTCOME_VETOED):
        path.notes.append("The official record marks this measure as passed; check the official actions.")
    path.current_key = next((s.key for s in steps if s.state == CURRENT), None)
    return path
