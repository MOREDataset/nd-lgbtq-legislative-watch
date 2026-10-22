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


# --- Rule fixes found by checking every 2023 bill (rules version 2026.10.2) ---


def _text(title, text):
    return classify(title=title, summary=None, texts=[("v1", text, None)])


def test_lowercase_aids_is_not_aids():
    r = _text("AN ACT relating to homestead exemptions",
              "Professionally prescribed health aids for the debtor. A person who aids or abets a crime.")
    assert r.status == "not_relevant"
    assert _text("AN ACT relating to public health", "testing for HIV and AIDS").status != "not_relevant"


def test_pronounce_is_not_pronoun():
    r = _text("AN ACT relating to the court of appeals", "A majority of the judges is necessary to pronounce a decision.")
    assert r.status == "not_relevant"


def test_hiv_in_medical_marijuana_condition_list_is_ignored():
    text = ('"Debilitating medical condition" means one of the following: a. Cancer; '
            "b. Positive status for human immunodeficiency virus; c. Glaucoma.")
    assert _text("AN ACT relating to edible cannabinoid products", text).status == "not_relevant"


def test_standard_protected_class_list_is_not_a_signal():
    text = ("It is a discriminatory practice for an employer to refuse to hire because of race, color, religion, sex, "
            "national origin, age, physical or mental disability, status with respect to marriage or public assistance.")
    assert _text("AN ACT relating to vaccination status", text).status == "not_relevant"


def test_list_that_adds_sexual_orientation_still_counts():
    text = "because of actual or perceived race, color, religion, gender, disability, sexual orientation, gender identity"
    assert _text("AN ACT relating to bias crimes", text).status == "relevant"


def test_same_rule_counts_once_across_versions():
    one = _text("AN ACT relating to definitions", '"Female" means an individual. ')
    two = classify(title="AN ACT relating to definitions", summary=None,
                   texts=[("v1", '"Female" means an individual.', None), ("v2", '"Male" means an individual.', None)])
    assert two.score == one.score


def test_parental_rights_and_sex_education_go_to_review():
    r = classify(title=None, summary="Relating to growth and development and human sexuality curriculum.")
    assert r.status == "possible"
