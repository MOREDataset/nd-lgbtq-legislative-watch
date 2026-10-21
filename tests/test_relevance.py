"""Relevance rules on SYNTHETIC text snippets (real-bill checks are in test_historical_2025.py)."""

from ndwatch.relevance.detector import classify, load_rules, normalize_text, referenced_sections


def test_title_keyword_is_direct():
    r = classify(title="AN ACT relating to gender-affirming care for minors", summary=None)
    assert r.status == "relevant" and r.level == "direct" and "healthcare" in r.topics


def test_context_word_alone_is_not_enough():
    r = classify(title="AN ACT relating to restroom facilities at highway rest areas", summary=None)
    assert r.status == "not_relevant"


def test_context_word_with_nearby_term_counts():
    text = "A public school shall designate each multiple-occupancy restroom for use by individuals of one sex."
    r = classify(title="AN ACT relating to school facilities", summary=None, texts=[("v1", text, None)])
    assert r.status in ("possible", "relevant") and "schools" in r.topics


def test_sex_offender_is_ignored():
    text = "The sex offender registry must include the offender's name. A sex offender may not live near a school."
    r = classify(title="AN ACT relating to sex offender registration", summary=None, texts=[("v1", text, None)])
    assert r.status == "not_relevant"


def test_hearing_aids_not_hiv():
    r = classify(title="AN ACT relating to insurance coverage of hearing aids", summary=None)
    assert r.status == "not_relevant"


def test_evidence_records_where_and_quote():
    text = "Ethics. It is not an ethical violation for a licensee to offer a plan that aligns with the individual's biological sex or gender identity."
    r = classify(title="AN ACT relating to licensing", summary=None, texts=[("25.0001.01000", text, "https://example.invalid/x.pdf")])
    ev = r.evidence[0]
    assert ev.where == "text" and ev.version == "25.0001.01000" and "biological sex" in r.evidence[0].snippet + r.evidence[1].snippet


def test_normalize_removes_line_numbers_and_hyphenation():
    raw = "1 a licensee may not offer conver-\n2 sion therapy\n3\n4"
    assert normalize_text(raw) == "a licensee may not offer conversion therapy"


def test_referenced_sections_from_title():
    t = "AN ACT to amend and reenact section 15.1-06-21 and to repeal section 12.1-20-17 of the North Dakota Century Code; and chapter 43-41"
    assert {"15.1-06-21", "12.1-20-17", "43-41"} <= referenced_sections(t)


def test_rules_are_configurable():
    rules = load_rules("""
version: test
thresholds: {relevant: 4, review: 2}
topics:
  t: {label: Test, terms: [{pattern: "snowmobile", weight: 2}]}
""")
    r = classify(title="snowmobile fees", summary=None, rules=rules)
    assert r.status == "relevant" and r.rules_version == "test"


def test_century_code_context_is_indirect():
    hits = {"43-41-99": [{"topic": "conversion", "term": "conversion therapy", "snippet": "a licensee may not engage in conversion therapy"}]}
    r = classify(title="AN ACT to amend and reenact section 43-41-99 of the North Dakota Century Code, relating to social work",
                 summary=None, century_code_hits=hits)
    assert r.status == "possible" and r.evidence[0].where == "century_code"
