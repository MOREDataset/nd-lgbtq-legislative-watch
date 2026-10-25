"""Plain-language explanations of legislative terms and official titles.

Everything here explains the *official* wording; it never adds facts. When the
official record does not say something, the explanation says so.
"""

from __future__ import annotations

import re

GLOSSARY: dict[str, str] = {
    "Introduced": "The bill was formally filed and read for the first time. This is the start of the process.",
    "First reading": "The bill's title was read aloud in the chamber. It is a formality that starts the process.",
    "Referred to committee": "The bill was sent to a smaller group of legislators (a committee) to study it, hold a public hearing, and recommend what to do.",
    "Committee hearing": "A public meeting where a committee hears from the bill's sponsor and the public. Anyone may submit testimony.",
    "Committee work session": "A meeting where the committee discusses and may amend or vote on its recommendation. The public may watch, but testimony is not taken online.",
    "Do pass": "The committee recommends that the full chamber pass the bill. It is a recommendation, not a final vote.",
    "Do not pass": "The committee recommends that the full chamber reject the bill. The full chamber still votes.",
    "Amendment": "A proposed change to the bill's wording. An amendment only changes the bill if it is adopted.",
    "Engrossed": "A new copy of the bill that includes amendments adopted so far.",
    "Enrolled": "The final text as passed by both chambers, prepared for the Governor.",
    "Second reading": "The full chamber debates and votes on the bill.",
    "Passed the House": "The House approved it. It does not become law until the Senate also passes it and the Governor acts.",
    "Passed the Senate": "The Senate approved it. It does not become law until the House also passes it and the Governor acts.",
    "Conference committee": "A small group from both chambers that tries to agree on one version when the House and Senate passed different ones.",
    "Concur": "To agree with changes the other chamber made.",
    "Veto": "The Governor rejected the bill. The Legislature can override a veto with a two-thirds vote of all members elected to each chamber.",
    "Filed with Secretary of State": "The final official step after the Governor acts (or a veto is overridden).",
    "Emergency clause": "A section saying the law should take effect as soon as it is filed instead of on the usual date. It needs yes votes from two-thirds of all members elected to each chamber.",
    "Constitutional majority": "To pass, a bill needs yes votes from a majority of all members elected to the chamber (48 of 94 in the House, 24 of 47 in the Senate), not just a majority of those voting. A bill can get more yes than no votes and still fail.",
    "Consent calendar": "A list of bills that a committee recommended without opposition. They are voted on without debate, and any legislator can ask to move a bill off the list.",
    "Crossover": "The deadline about halfway through the session. Most bills must pass the chamber where they started by this date, or they stop.",
    "Laid over": "The vote or decision was postponed for one or more legislative days.",
    "Item veto": "The Governor can veto individual parts of a spending bill while signing the rest.",
    "Referral (referendum)": "After a new law is filed, citizens can petition to put it to a statewide vote. A successful petition puts the law on hold until the vote.",
    "Interim": "The time between regular sessions. Legislative committees meet to study topics and prepare bill drafts for the next session.",
    "Roll call vote": "A recorded vote showing how each legislator voted.",
    "Century Code": "The North Dakota Century Code is the collection of the state's current laws. Bills add to, change, or remove parts of it.",
    "Resolution": "A formal statement or request by the Legislature. Most resolutions do not become law the way bills do.",
    "Constitutional amendment resolution": "A concurrent resolution that proposes changing the North Dakota Constitution. It does not go to the Governor. If both chambers adopt it, it goes to the voters at a statewide election and takes effect only if voters approve it.",
}

KIND_NAMES = {
    "HB": "House Bill",
    "SB": "Senate Bill",
    "HCR": "House Concurrent Resolution",
    "SCR": "Senate Concurrent Resolution",
    "HR": "House Resolution",
    "SR": "Senate Resolution",
    "HMR": "House Memorial Resolution",
    "SMR": "Senate Memorial Resolution",
}

IMPACT_LABELS = {
    "expands": "May expand access or protections",
    "restricts": "May restrict access or protections",
    "administrative": "Changes administrative requirements",
    "mixed": "Mixed effects",
    "unclear": "Impact unclear or requires review",
}


def explain_status(status: str | None) -> str:
    """One-sentence plain meaning of the official `current_status`."""
    if not status:
        return "The official record does not list a status."
    s = status.lower()
    rules = [
        ("governor signed", "The Governor signed it. It is (or will become) law."),
        ("filed with secretary", "It completed the process and was filed as law."),
        ("veto", "The Governor vetoed it."),
        ("failed", "It did not pass."),
        ("passed", "It passed. Check the path below to see whether it still needs another step."),
        ("committee", "It is being reviewed by a committee."),
        ("introduced", "It was introduced and has not had a vote yet."),
        ("withdrawn", "It was withdrawn by its sponsor."),
        ("adopted", "It was adopted."),
    ]
    for key, text in rules:
        if key in s:
            return text
    return "See the official actions for details."


_ACT_PARTS = [
    (r"to create and enact ([^;:]+)", "add new law", "Adds new law: {}"),
    (r"to amend and reenact ([^;:]+)", "change existing law", "Changes existing law: {}"),
    (r"to repeal ([^;:]+)", "remove existing law", "Removes existing law: {}"),
    (r"to provide (?:a|an) penalt", "penalty", "Includes a penalty (a punishment for breaking the new rule)."),
    (r"to provide an appropriation|appropriation for", "money", "Spends state money (an appropriation)."),
    (r"to provide (?:an|for an?) (?:effective|expiration) date", "dates", "Sets its own effective or expiration date."),
    (r"to declare an emergency", "emergency", "Declares an emergency, which lets it take effect sooner if it passes with the larger vote required."),
    (r"to provide for (?:a )?(?:legislative management |)study", "study", "Calls for a study."),
]


def what_would_change(title: str | None) -> list[str]:
    """Break an official 'AN ACT to ...' title into plain statements. Facts come only from the title."""
    if not title:
        return []
    t = re.sub(r"\s+", " ", title)
    out: list[str] = []
    for pattern, _key, template in _ACT_PARTS:
        for m in re.finditer(pattern, t, re.I):
            if "{}" in template:
                target = re.split(r",\s*(?:relating to|to |and to )", m.group(1), maxsplit=1)[0].strip().rstrip(",")
                target = re.sub(r",? of the North Dakota Century Code", " of the North Dakota Century Code", target)
                out.append(template.format(target))
            else:
                out.append(template)
                break
    # De-duplicate while keeping order.
    seen, result = set(), []
    for line in out:
        if line not in seen:
            seen.add(line)
            result.append(line)
    return result


def headline(summary: str | None, fallback: str) -> str:
    """The subject part of the official summary: 'Relating to X; to provide a penalty.' -> 'Relating to X.'"""
    if not summary:
        return fallback
    first = summary.split(";")[0].strip().rstrip(".")
    return first + "."


def about_line(summary: str | None, title: str | None) -> str:
    """Turn 'Relating to X.' into 'This bill deals with X.'"""
    text = (summary or "").strip()
    if not text and title:
        m = re.search(r"relating to ([^;.]+)", title, re.I)
        text = f"Relating to {m.group(1)}" if m else ""
    if not text:
        return "The official record does not include a short description."
    text = text.split(";")[0]
    text = re.sub(r"^\s*relating to\s+", "", text, flags=re.I).rstrip(". ")
    return f"This bill deals with {text}."


def century_code_links(title: str | None) -> list[tuple[str, str]]:
    """Century Code sections/chapters named in the title, with links to the official code."""
    if not title:
        return []
    out = []
    for m in re.finditer(r"\b(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?\b", title):
        t, c, s = m.group(1), m.group(2), m.group(3)
        label = f"Section {t}-{c}-{s}" if s else f"Chapter {t}-{c}"
        # The official code is published as one PDF per chapter.
        url = f"https://ndlegis.gov/cencode/t{t.replace('.', '-')}c{c.replace('.', '-')}.pdf"
        out.append((label, url))
    seen, result = set(), []
    for lab, url in out:
        if lab not in seen:
            seen.add(lab)
            result.append((lab, url))
    return result[:12]


def kind_name(kind: str | None) -> str:
    return KIND_NAMES.get((kind or "").upper(), "Measure")


# ------------------------------------------------------------------ official actions in plain words

_COUNTS = r"(\d+)\s+(\d+)\s+(\d+)\s*$"


def _committee_counts(d: str) -> str:
    m = re.search(_COUNTS, d)
    if not m:
        return ""
    y, n, a = m.groups()
    return f" (committee vote on this recommendation: {y} yes, {n} no, {a} absent)"


def _floor_counts(d: str) -> str:
    m = re.search(r"yeas\s+(\d+)\s+nays\s+(\d+)", d, re.I)
    return f", {m.group(1)} to {m.group(2)}" if m else ""


def explain_action(description: str | None, chamber: str | None = None) -> str | None:
    """One plain-English sentence for an official action line, or None if we have no safe wording.

    It restates only what the official line says. The official text is always shown next to it.
    """
    d = re.sub(r"\s+", " ", (description or "")).strip()
    if not d:
        return None
    low = d.lower()
    ch = chamber if chamber in ("House", "Senate") else "chamber"
    the_ch = f"the {ch}"
    The_ch = f"The {ch}"

    m = re.match(r"introduced, first reading,(?: \(emergency\),)? referred (.+?)(?: committee)?$", d, re.I)
    if m:
        out = f"Introduced in {the_ch} and sent to the {m.group(1)} Committee, which will hold a public hearing."
        if "(emergency)" in low:
            out += " The bill includes an emergency clause."
        return out
    if low.startswith("introduced, first reading"):
        return f"Introduced in {the_ch}."
    if low.startswith("committee hearing"):
        return "Public hearing in committee, where the sponsor and members of the public can speak."
    if low.startswith("reported back from conference committee"):
        return "The conference committee (members of both chambers) reported back on the differences between the House and Senate versions."
    if low.startswith("reported back") or low.startswith("engrossment placed"):
        if low.startswith("engrossment placed"):
            return "A new copy of the bill with the adopted changes was prepared for the full chamber's vote" + _committee_counts(d) + "."
        amended = " with changes to its wording" if "amended" in low else ""
        if "do not pass" in low:
            rec = f"The committee recommended that {the_ch} reject the bill{amended}"
        elif "do pass" in low:
            rec = f"The committee recommended that {the_ch} pass the bill{amended}"
        elif "without recommendation" in low:
            rec = f"The committee sent the bill{amended} to the full {ch} without a recommendation"
        else:
            return None
        out = rec + _committee_counts(d) + ". This is a recommendation; the full " + ch + " still votes."
        if "consent calendar" in low:
            out += " It was placed on the consent calendar, a list of bills voted on without debate."
        return out
    if low.startswith("amendment adopted"):
        return f"{The_ch} accepted the proposed changes to the bill's wording."
    if low.startswith("amendment failed"):
        return "A proposed change to the bill's wording was rejected."
    if low.startswith("amendment proposed on floor"):
        return "A legislator proposed a change to the wording during floor debate."
    if low.startswith("second reading"):
        votes = _floor_counts(d)
        if "lacks constitutional majority" in low:
            return (f"The full {ch} voted{votes}, but the bill did not get yes votes from a majority of all "
                    "elected members, which the state constitution requires, so it failed.")
        if re.search(r"failed to (pass|adopt)|, failed\b", low):
            out = f"The full {ch} voted it down{votes}."
        elif "passed as amended" in low or "adopted as amended" in low:
            out = f"The full {ch} approved it with changes{votes}."
        elif "passed" in low or "adopted" in low:
            out = f"The full {ch} approved it{votes}."
        else:
            return None
        if "emergency clause carried" in low:
            out += " The emergency clause also got the two-thirds vote it needs."
        elif "emergency clause failed" in low:
            out += " The emergency clause did not get the two-thirds vote it needs."
        return out
    if low.startswith("emergency clause carried"):
        return "The emergency clause got the two-thirds vote it needs, so the bill can take effect as soon as it is filed."
    if low.startswith("emergency clause failed"):
        return "The emergency clause did not get the two-thirds vote it needs, so the bill cannot take effect early."
    m = re.match(r"received from (house|senate)", low)
    if m:
        return f"Arrived in {the_ch} after passing the {m.group(1).capitalize()}. The same steps now happen here."
    m = re.match(r"rereferred to (.+)$", d, re.I)
    if m:
        out = f"Sent to the {m.group(1)} Committee for more review."
        if "appropriations" in m.group(1).lower():
            out += " The Appropriations Committee looks at bills that spend state money."
        return out
    m = re.match(r"returned to (house|senate)", low)
    if m:
        return f"Sent back to the {m.group(1).capitalize()}."
    if low.startswith("refused to concur"):
        return f"{The_ch} did not agree to the other chamber's changes. A conference committee usually follows."
    if low.startswith("concurred"):
        return f"{The_ch} agreed to the other chamber's changes."
    m = re.match(r"appoint (.+?) to replace (.+?) on conference committee", d, re.I)
    if m:
        return f"Conference committee membership changed: {m.group(1)} replaces {m.group(2)}."
    if low.startswith("conference committee dissolved"):
        return "The conference committee was dissolved."
    m = re.match(r"(?:new )?conference committee appointed (.+)$", d, re.I)
    if m:
        return f"Legislators named to the conference committee, which works out differences between the chambers: {m.group(1)}."
    if low.startswith("conference committee report adopted"):
        return f"{The_ch} accepted the conference committee's compromise."
    if low.startswith("conference committee report rejected"):
        return f"{The_ch} rejected the conference committee's compromise."
    if low.startswith("signed by speaker"):
        return "Signed by the Speaker of the House, a formal step after both chambers pass it."
    if low.startswith("signed by president"):
        return "Signed by the President of the Senate, a formal step after both chambers pass it."
    if low.startswith("sent to governor"):
        return "Sent to the Governor, who can sign it, veto it, or let it become law without signing."
    if re.match(r"signed by governor, but item veto", low):
        return "The Governor signed it but vetoed some parts (an item veto)."
    if low.startswith("signed by governor"):
        return "The Governor signed it."
    if low.startswith("vetoed by governor"):
        return "The Governor vetoed (rejected) it. The Legislature can override with a two-thirds vote in each chamber."
    if low.startswith("consideration of governor's veto"):
        return f"{The_ch} considered whether to override the Governor's veto."
    if low.startswith("veto sustained"):
        return f"The attempt to override the veto failed{_floor_counts(d)}, so the veto stands."
    if low.startswith("passed over veto"):
        return (f"{The_ch} voted to override the Governor's veto{_floor_counts(d)}. "
                "The veto is overridden only if both chambers do this with a two-thirds vote.")
    if low.startswith("veto overridden"):
        return f"The veto was overridden{_floor_counts(d)}."
    if low.startswith("filed with secretary of state"):
        return "Filed with the Secretary of State, the last official step."
    m = re.match(r"laid over (\w+) legislative days?", low)
    if m:
        return f"The decision was postponed by {m.group(1)} legislative day{'s' if m.group(1) != 'one' else ''}."
    if low.startswith("motion to reconsider failed"):
        return "A motion to vote again failed, so the earlier result stands."
    if low.startswith("reconsidered"):
        return f"{The_ch} agreed to take its earlier vote again."
    if low.startswith("withdrawn from further consideration"):
        return "Withdrawn. The bill will not move forward."
    if low.startswith("division of"):
        return f"{The_ch} split the {'amendment' if 'amendment' in low else 'bill'} into parts to vote on them separately."
    m = re.match(r"division (\w+) (passed|adopted|lost)", low)
    if m:
        res = "was approved" if m.group(2) in ("passed", "adopted") else "was rejected"
        return f"Part {m.group(1).upper()} {res} in a separate vote."
    return None


def effective_date_note(title: str | None, session_name: str | None, emergency_clause: bool | None) -> str:
    """When a law that passed takes effect, stated only as far as the record and state law support."""
    t = (title or "").lower()
    parts = []
    if emergency_clause is True:
        parts.append("Its emergency clause passed, so it took effect when it was filed with the Secretary of State, "
                     "unless the bill names a different date.")
    else:
        if emergency_clause is False:
            parts.append("Its emergency clause did not get the two-thirds vote it needs, so it does not take effect early.")
        elif "declare an emergency" in t:
            parts.append("The title says it declares an emergency, which can make it take effect as soon as it is filed.")
        if "effective date" in t or "expiration date" in t:
            parts.append("The bill sets its own effective or expiration date; the bill text has the exact date.")
        elif "special" not in (session_name or "").lower():
            parts.append("Unless a bill says otherwise, a new North Dakota law from a regular session takes effect on "
                         "August 1 after the session.")
    return " ".join(parts)
