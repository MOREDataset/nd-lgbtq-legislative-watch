"""HTML parsers on SYNTHETIC pages (real pages are covered in test_historical_2025.py)."""

from ndwatch.explain import about_line, what_would_change
from ndwatch.sources.pages import extract_pdf_text, parse_public_schedule, parse_testimony_page
from tests.fixtures.synthetic import factory as syn


def test_testimony_rows_and_broken_row():
    rows, warnings = parse_testimony_page(syn.TESTIMONY_HTML, "https://ndlegis.gov/x")
    assert [r.document_number for r in rows] == ["10001", "10002"]
    assert rows[0].position == "In Opposition" and rows[0].organization == "Example Org"
    assert warnings  # the row without a document link is reported, not invented


def test_schedule_rules():
    r = parse_public_schedule(syn.SCHEDULE_HTML)
    assert r.deadline_rule and "one hour before" in r.deadline_rule
    assert r.how_to_submit_url.endswith("how_to_submit_bill_testimony.pdf")


def test_schedule_without_rule_returns_none():
    assert parse_public_schedule("<html><p>Nothing here</p></html>").deadline_rule is None


def test_bad_pdf_is_reported():
    assert not extract_pdf_text(b"<html>not a pdf</html>").ok


def test_plain_language_title():
    lines = what_would_change("AN ACT to create and enact a new section to chapter 43-41 of the North Dakota Century Code, relating to the regulation of social workers; and to provide a penalty.")
    assert lines[0] == "Adds new law: a new section to chapter 43-41 of the North Dakota Century Code"
    assert any("penalty" in x for x in lines)
    assert about_line("Relating to the regulation of social workers.", None) == "This bill deals with the regulation of social workers."
    assert about_line(None, None).startswith("The official record does not include")
