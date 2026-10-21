"""Parsing of official API shapes (synthetic data with the real structure)."""

import json

from ndwatch.sources.api import LegislativeApi, fix_source_url
from ndwatch.sources.api_models import ApiBills, ApiRollCalls
from ndwatch.sources.http import DictFetcher
from tests.fixtures.synthetic import factory as syn


def test_bills_object_keyed_by_number_parses():
    data = ApiBills.model_validate(syn.bills(syn.bill_school(), syn.bill_licensing()))
    bills = data.bill_list()
    assert [b.name for b in bills] == ["HB 9001", "HB 9002"]
    assert bills[0].actions[0].roll_call is None  # API sends {} for "no vote"
    assert bills[0].sponsors[0].primary is True


def test_missing_fields_stay_missing_not_invented():
    b = syn.bill_school(summary="", agency=None, passed=None)
    data = ApiBills.model_validate(syn.bills(b))
    bill = data.bill_list()[0]
    assert bill.summary is None
    assert bill.passed is None
    assert bill.agency is None


def test_roll_call_with_member_votes():
    rc = {
        "id": "209701H00001", "session_id": "209701", "bill": "HB 9001", "bill_version": "97.0001.01000",
        "chamber": "House", "date": "2097-02-07T14:00:00", "description": "Final Passage", "division": None,
        "passed": True, "total_yeas": 1, "total_nays": 1, "total_absent": 0,
        "member_votes": [{"member_id": 1, "name": "Example, Alex", "vote": "Yea"},
                         {"member_id": 3, "name": "Other, Pat", "vote": "Nay"}],
    }
    data = ApiRollCalls.model_validate(syn.roll_calls(rc))
    assert data.roll_call[0].member_votes[1].vote == "Nay"


def test_malformed_json_is_reported_not_raised():
    url = "https://ndlegis.gov/api/assembly/99-2097/data/bills.json"
    api = LegislativeApi(DictFetcher({url: b"{not json"}))
    parsed = api.bills("99-2097")
    assert not parsed.ok and "invalid JSON" in parsed.error


def test_wrong_shape_is_reported():
    url = "https://ndlegis.gov/api/assembly/99-2097/data/bills.json"
    api = LegislativeApi(DictFetcher({url: json.dumps({"bills": {}}).encode()}))
    parsed = api.bills("99-2097")
    assert not parsed.ok and "unexpected format" in parsed.error


def test_new_fields_produce_drift_warning():
    b = syn.bill_school(brand_new_field="x")
    url = "https://ndlegis.gov/api/assembly/99-2097/data/bills.json"
    api = LegislativeApi(DictFetcher({url: syn.to_bytes(syn.bills(b))}))
    parsed = api.bills("99-2097")
    assert parsed.ok
    assert any("brand_new_field" in w for w in parsed.warnings)


def test_assemblies_discovered_dynamically():
    api = LegislativeApi(DictFetcher({"https://ndlegis.gov/api/data/assemblies.json": syn.to_bytes(syn.assemblies(include_next=True))}))
    parsed = api.assemblies()
    assert {a.year for a in parsed.data} == {"99-2097", "100-2099"}


def test_fix_source_url_only_repairs_missing_slash():
    assert fix_source_url("https://ndlegis.govassembly/69-2025/x.html") == "https://ndlegis.gov/assembly/69-2025/x.html"
    assert fix_source_url("https://ndlegis.gov/assembly/69-2025/x.html") == "https://ndlegis.gov/assembly/69-2025/x.html"
