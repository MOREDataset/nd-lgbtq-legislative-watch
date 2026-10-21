"""Layered relevance detection.

Layer A: configurable terms checked against the official title and summary.
Layer B: the same rules checked against the full text of every published bill
         version (so a bill with a generic title, like a professional-licensing
         bill, is still found when its text touches these topics), plus
         context rules that only count a word when related words are nearby.
Layer C: Century Code context. If a bill amends or repeals a Century Code
         section whose current text matches the rules, that is recorded as
         indirect evidence.
Optional: an AI classifier can add evidence through `extra_evidence`, but it is
never required and its evidence is labeled as such.

Every flag records *why*: the matched words, where they were found, and a short
quote of the surrounding official text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

RELEVANT, POSSIBLE, NOT_RELEVANT = "relevant", "possible", "not_relevant"
DIRECT, INDIRECT, UNCERTAIN = "direct", "indirect", "uncertain"


@dataclass
class Term:
    topic: str
    pattern: re.Pattern
    weight: int
    near: list[re.Pattern]
    unless: list[re.Pattern]
    raw: str


@dataclass
class Rules:
    version: str
    relevant: int
    review: int
    window: int
    topics: dict[str, str]  # key -> label
    terms: list[Term]
    global_unless: list[re.Pattern]


@dataclass
class Evidence:
    topic: str
    term: str
    where: str  # "title" | "summary" | "text" | "century_code" | "ai"
    snippet: str
    weight: int
    version: str | None = None
    url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "term": self.term,
            "where": self.where,
            "snippet": self.snippet,
            "weight": self.weight,
            "version": self.version,
            "url": self.url,
        }


@dataclass
class Result:
    status: str
    level: str | None
    score: int
    topics: list[str]
    evidence: list[Evidence] = field(default_factory=list)
    rules_version: str = ""


def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.IGNORECASE)


def load_rules(text: str | None = None) -> Rules:
    if text is None:
        text = resources.files("ndwatch.relevance").joinpath("topics.yaml").read_text("utf-8")
    cfg = yaml.safe_load(text)
    terms: list[Term] = []
    topics: dict[str, str] = {}
    for key, topic in cfg["topics"].items():
        topics[key] = topic["label"]
        for t in topic["terms"]:
            terms.append(
                Term(
                    topic=key,
                    pattern=_rx(t["pattern"]),
                    weight=int(t.get("weight", 1)),
                    near=[_rx(p) for p in t.get("near", [])],
                    unless=[_rx(p) for p in t.get("unless", [])],
                    raw=t["pattern"],
                )
            )
    return Rules(
        version=str(cfg.get("version", "0")),
        relevant=int(cfg["thresholds"]["relevant"]),
        review=int(cfg["thresholds"]["review"]),
        window=int(cfg.get("window", 160)),
        topics=topics,
        terms=terms,
        global_unless=[_rx(p) for p in cfg.get("global_unless", [])],
    )


@lru_cache(maxsize=1)
def default_rules() -> Rules:
    return load_rules()


_LINE_NUMBER = re.compile(r"(?m)^\s*\d{1,2}\s+")


def normalize_text(text: str) -> str:
    """Clean text extracted from a bill PDF: drop margin line numbers, rejoin hyphenated words."""
    text = _LINE_NUMBER.sub("", text)
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _mask(text: str, patterns: list[re.Pattern]) -> str:
    for p in patterns:
        text = p.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _snippet(text: str, start: int, end: int, pad: int = 110) -> str:
    a = max(0, start - pad)
    b = min(len(text), end + pad)
    s = text[a:b].strip()
    return ("…" if a > 0 else "") + s + ("…" if b < len(text) else "")


def _scan(text: str, where: str, rules: Rules, version: str | None, url: str | None) -> list[Evidence]:
    if not text:
        return []
    masked = _mask(text, rules.global_unless)
    found: list[Evidence] = []
    for term in rules.terms:
        hits = 0
        for m in term.pattern.finditer(masked):
            lo, hi = max(0, m.start() - rules.window), min(len(masked), m.end() + rules.window)
            ctx = masked[lo:hi]
            if term.unless and any(u.search(ctx) for u in term.unless):
                continue
            if term.near and not any(n.search(ctx) for n in term.near):
                continue
            hits += 1
            if hits == 1:
                found.append(
                    Evidence(
                        topic=term.topic,
                        term=m.group(0),
                        where=where,
                        snippet=_snippet(text, m.start(), m.end()),
                        weight=term.weight,
                        version=version,
                        url=url,
                    )
                )
            if hits >= 3:
                break
        if hits > 1:
            # Repeated mentions add a little, with diminishing returns.
            found[-1].weight += min(hits - 1, 2)
    return found


SECTION_RX = re.compile(r"\b(?:section|subsection \d+ of section)s?\s+((?:\d+(?:\.\d+)?-\d+(?:\.\d+)?-\d+(?:\.\d+)?)(?:\s*(?:,|and)\s*\d+(?:\.\d+)?-\d+(?:\.\d+)?-\d+(?:\.\d+)?)*)", re.I)
CHAPTER_RX = re.compile(r"\bchapters?\s+(\d+(?:\.\d+)?-\d+(?:\.\d+)?)", re.I)


def referenced_sections(title: str | None) -> set[str]:
    """Century Code sections/chapters a bill's title says it creates, amends, or repeals."""
    if not title:
        return set()
    out: set[str] = set()
    for m in SECTION_RX.finditer(title):
        out.update(re.findall(r"\d+(?:\.\d+)?-\d+(?:\.\d+)?-\d+(?:\.\d+)?", m.group(1)))
    for m in CHAPTER_RX.finditer(title):
        out.add(m.group(1))
    return out


def classify(
    *,
    title: str | None,
    summary: str | None,
    texts: list[tuple[str, str, str | None]] | None = None,  # (lc_number, text, url)
    century_code_hits: dict[str, list[dict]] | None = None,  # section -> [{topic, term, snippet, url}]
    extra_evidence: list[Evidence] | None = None,
    rules: Rules | None = None,
) -> Result:
    rules = rules or default_rules()
    evidence: list[Evidence] = []

    for where, text in (("title", title or ""), ("summary", summary or "")):
        for ev in _scan(text, where, rules, None, None):
            ev.weight *= 2
            evidence.append(ev)

    # Full text: count each term once across versions (keep the newest version's quote).
    text_ev: dict[tuple[str, str], Evidence] = {}
    for lc, raw, url in reversed(texts or []):
        norm = normalize_text(raw)
        for ev in _scan(norm, "text", rules, lc, url):
            key = (ev.topic, ev.term.lower())
            if key not in text_ev or ev.weight > text_ev[key].weight:
                text_ev[key] = ev
    # Skip text hits already proven by the title/summary to avoid double counting.
    title_terms = {(e.topic, e.term.lower()) for e in evidence}
    evidence.extend(e for k, e in text_ev.items() if k not in title_terms)

    if century_code_hits:
        for section in sorted(referenced_sections(title)):
            for hit in century_code_hits.get(section, [])[:2]:
                evidence.append(
                    Evidence(
                        topic=hit["topic"],
                        term=hit["term"],
                        where="century_code",
                        snippet=f"Changes N.D.C.C. § {section}, which currently says: {hit['snippet']}",
                        weight=3,
                        url=hit.get("url"),
                    )
                )

    evidence.extend(extra_evidence or [])

    # Score: best evidence per (topic, term) already deduped; cap each topic so
    # one heavily repeated topic cannot dominate.
    per_topic: dict[str, int] = {}
    for e in evidence:
        per_topic[e.topic] = per_topic.get(e.topic, 0) + e.weight
    score = sum(min(v, 20) for v in per_topic.values())

    strong_in_title = any(e.where in ("title", "summary") and e.weight >= 8 for e in evidence)
    strong_text = [e for e in evidence if e.where == "text" and e.weight >= 5]
    if strong_in_title or len(strong_text) >= 2 or (strong_text and score >= rules.relevant):
        level = DIRECT
    elif score >= rules.relevant:
        level = INDIRECT
    elif score >= rules.review:
        level = UNCERTAIN
    else:
        level = None

    if level == DIRECT or score >= rules.relevant:
        status = RELEVANT
    elif score >= rules.review:
        status = POSSIBLE
    else:
        status = NOT_RELEVANT

    topics = sorted(per_topic, key=lambda t: -per_topic[t])
    evidence.sort(key=lambda e: (-e.weight, e.where))
    return Result(status=status, level=level, score=score, topics=topics, evidence=evidence, rules_version=rules.version)
