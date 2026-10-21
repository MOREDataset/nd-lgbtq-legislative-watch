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
    "Veto": "The Governor rejected the bill. The Legislature can override a veto with a two-thirds vote in each chamber.",
    "Filed with Secretary of State": "The final official step after the Governor acts (or a veto is overridden).",
    "Emergency clause": "A section saying the law should take effect sooner than usual. It needs a larger majority to pass.",
    "Roll call vote": "A recorded vote showing how each legislator voted.",
    "Century Code": "The North Dakota Century Code is the collection of the state's current laws. Bills add to, change, or remove parts of it.",
    "Resolution": "A formal statement or request by the Legislature. Most resolutions do not become law the way bills do.",
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
                target = m.group(1).strip().rstrip(",")
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


def about_line(summary: str | None, title: str | None) -> str:
    """Turn 'Relating to X.' into 'This bill deals with X.'"""
    text = (summary or "").strip()
    if not text and title:
        m = re.search(r"relating to ([^;.]+)", title, re.I)
        text = f"Relating to {m.group(1)}" if m else ""
    if not text:
        return "The official record does not include a short description."
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
