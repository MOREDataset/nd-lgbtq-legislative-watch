"""SYNTHETIC test data. NOT real legislative records.

Everything here uses the fictional "99th Legislative Assembly (2097-2099)" and
bill numbers in the 9000s so it can never be mistaken for real North Dakota
legislation. The shapes match the official API (see docs/SOURCES.md).
Real 2025 records used for validation live in tests/fixtures/historical/.
"""

from __future__ import annotations

import copy
import json

ASSEMBLY = "99-2097"
BASE = "https://ndlegis.gov"


def assemblies(current_session: str = "209701", include_next: bool = False) -> dict:
    data = {
        "99": {
            "assembly": 99,
            "assembly_name": "99th Legislative Assembly (SYNTHETIC)",
            "assembly_year": ASSEMBLY,
            "biennium_start": 2097,
            "biennium_end": 2099,
            "last_updated": "2097-02-01T10:00:00",
            "sessions": sessions()["sessions"],
        }
    }
    for s in data["99"]["sessions"]:
        s["current"] = s["id"] == current_session
    if include_next:
        data["100"] = {
            "assembly": 100,
            "assembly_name": "100th Legislative Assembly (SYNTHETIC)",
            "assembly_year": "100-2099",
            "biennium_start": 2099,
            "biennium_end": 2101,
            "last_updated": "2098-12-01T10:00:00",
            "sessions": [],
        }
    return data


def sessions() -> dict:
    return {
        "assembly": 99,
        "assembly_name": "99th Legislative Assembly (SYNTHETIC)",
        "biennium_start": 2097,
        "biennium_end": 2099,
        "last_updated": "2097-02-01T10:00:00",
        "sessions": [
            {"id": "209701", "name": "2097 Regular Session", "type": "Regular", "label": "Regular",
             "folder": "regular", "current": True, "start": "2097-01-07"},
            {"id": "209702", "name": "Special Session - Nov 2097", "type": "Special", "label": "Special",
             "folder": "special", "current": False, "start": "2097-11-02"},
        ],
    }


def members() -> dict:
    return {
        "assembly": 99, "biennium_start": 2097, "last_updated": "2097-01-01T00:00:00",
        "members": [
            {"id": 1, "name": "Example, Alex", "salutation": "Representative", "chamber": "House",
             "party": "Republican", "district": "4A", "url": f"{BASE}/biography/example-alex", "active": True},
            {"id": 2, "name": "Sample, Jordan", "salutation": "Senator", "chamber": "Senate",
             "party": "Democratic", "district": 12, "url": f"{BASE}/biography/sample-jordan", "active": True},
        ],
    }


def _bill_urls(num: str, folder: str = "regular") -> dict:
    root = f"https://ndlegis.govassembly/{ASSEMBLY}/{folder}"  # the API really omits a slash here
    return {
        "url": f"{BASE}/assembly/{ASSEMBLY}/{folder}/bill-overview/bo{num}.html",
        "versions_url": f"{root}/bill-index/bi{num}.html",
        "actions_url": f"{root}/bill-actions/ba{num}.html",
        "video_url": f"{root}/bill-video/bv{num}.html",
        "hearing_url": f"{root}/bill-hearings/bh{num}.html",
        "testimony_url": f"{root}/bill-testimony/bt{num}.html",
    }


def bill_school(**over) -> dict:
    """A synthetic bill whose title directly mentions the topic."""
    b = {
        "name": "HB 9001",
        "number": "9001",
        "summary": "Relating to transgender student accommodations in public schools.",
        "title": "AN ACT to amend and reenact section 15.1-99-01 of the North Dakota Century Code, relating to transgender student accommodations in public schools.",
        "chamber": "House",
        "session_id": "209701",
        "session_name": "2097 Regular Session",
        **_bill_urls("9001"),
        "current_status": "In Committee",
        "last_action": "Introduced, first reading, referred Education Committee 01/07",
        "passed": None,
        "agency": None,
        "sponsors": [
            {"id": 1, "name": "Rep. Example", "type": "member", "chamber": "House", "primary": True},
            {"id": 2, "name": "Sen. Sample", "type": "member", "chamber": "Senate", "primary": False},
        ],
        "actions": [
            {"id": 1001, "description": "Introduced, first reading, referred Education Committee",
             "date": "2097-01-07T23:59:59", "category": "Introduced", "chamber": "House",
             "bill_version": "97.0001.01000", "roll_call": {}},
        ],
        "versions": [
            {"lc_number": "97.0001.01000", "description": "INTRODUCED",
             "document_url": f"{BASE}/assembly/{ASSEMBLY}/regular/documents/97-0001-01000.pdf"},
        ],
        "hearings": [],
    }
    b.update(over)
    return b


def bill_licensing(**over) -> dict:
    """A synthetic bill with a generic title; relevance only appears in its text."""
    b = {
        "name": "HB 9002",
        "number": "9002",
        "summary": "Relating to licensure of counselors.",
        "title": "AN ACT to amend and reenact section 43-99-02 of the North Dakota Century Code, relating to licensure of counselors.",
        "chamber": "House",
        "session_id": "209701",
        "session_name": "2097 Regular Session",
        **_bill_urls("9002"),
        "current_status": "In Committee",
        "last_action": "Introduced",
        "passed": None,
        "agency": None,
        "sponsors": [{"id": 1, "name": "Rep. Example", "type": "member", "chamber": "House", "primary": True}],
        "actions": [
            {"id": 2001, "description": "Introduced, first reading, referred Human Services Committee",
             "date": "2097-01-08T23:59:59", "category": "Introduced", "chamber": "House",
             "bill_version": "97.0002.01000", "roll_call": {}},
        ],
        "versions": [
            {"lc_number": "97.0002.01000", "description": "INTRODUCED",
             "document_url": f"{BASE}/assembly/{ASSEMBLY}/regular/documents/97-0002-01000.pdf"},
        ],
        "hearings": [],
    }
    b.update(over)
    return b


def bill_unrelated(**over) -> dict:
    b = bill_licensing(
        name="SB 9003", number="9003", chamber="Senate",
        summary="Relating to snowmobile registration fees.",
        title="AN ACT to amend and reenact section 39-99-03 of the North Dakota Century Code, relating to snowmobile registration fees.",
        actions=[{"id": 3001, "description": "Introduced, first reading, referred Transportation Committee",
                  "date": "2097-01-09T23:59:59", "category": "Introduced", "chamber": "Senate",
                  "bill_version": "97.0003.01000", "roll_call": {}}],
        versions=[{"lc_number": "97.0003.01000", "description": "INTRODUCED",
                   "document_url": f"{BASE}/assembly/{ASSEMBLY}/regular/documents/97-0003-01000.pdf"}],
        **_bill_urls("9003"),
    )
    b.update(over)
    return b


def bills(*items: dict) -> dict:
    return {
        "assembly": 99, "assembly_name": "99th Legislative Assembly (SYNTHETIC)",
        "biennium_start": 2097, "biennium_end": 2099, "last_updated": "2097-02-01T10:00:00",
        "bills": {b["number"]: copy.deepcopy(b) for b in items},
    }


def roll_calls(*items: dict) -> dict:
    return {"assembly": 99, "last_updated": "2097-02-01T10:00:00", "roll_call": list(items)}


def hearing(hid: int, date: str, room: str = "Pioneer", type_: str = "Bill Hearing") -> dict:
    return {"id": hid, "description": "SYNTHETIC hearing", "type": type_, "date": date,
            "committee": {"id": 77, "name": "House Education"}, "room": room}


def to_bytes(obj) -> bytes:
    return json.dumps(obj).encode()


def api_responses(bills_obj: dict, *, rolls: dict | None = None, assemblies_obj: dict | None = None) -> dict:
    a = f"{BASE}/api/assembly/{ASSEMBLY}/data"
    return {
        f"{BASE}/api/data/assemblies.json": to_bytes(assemblies_obj or assemblies()),
        f"{a}/sessions.json": to_bytes(sessions()),
        f"{a}/members.json": to_bytes(members()),
        f"{a}/bills.json": to_bytes(bills_obj),
        f"{a}/roll_call.json": to_bytes(rolls or roll_calls()),
        "https://www.ndlegis.gov/legend/committee/hearings/public-schedule/": SCHEDULE_HTML.encode(),
    }


SCHEDULE_HTML = """<html><body><h1>Committee Hearing Schedule (SYNTHETIC)</h1>
<p>Showing hearings from January 08, 2097 to January 12, 2097.</p>
<p>The deadline to submit testimony for public hearings is one hour before the start of the committee hearing.
Testimony may not be submitted online for committee work sessions.</p>
<a href="/sites/default/files/documents/how_to_submit_bill_testimony.pdf">How to Submit Online Testimony</a>
<table><tr><th>Hearing Date/Time</th><th>Bill</th></tr><tr><td>01/08 10:00 AM</td><td>HB 9001</td></tr></table>
</body></html>"""

TESTIMONY_HTML = """<html><body><table>
<tr><th>Hearing Date</th><th>Time</th><th>Committee</th><th>Name</th><th>Organization</th><th>Role</th>
<th>City | State</th><th>Position</th><th>Document Number</th></tr>
<tr><td>01/20</td><td>10:00 AM</td><td><a href="#">House Education</a></td><td>Pat Example</td><td>Example Org</td>
<td></td><td>Fargo, ND</td><td>In Opposition</td>
<td><a href="https://ndlegis.gov/assembly/99-2097/testimony/HEDU-9001-20970120-10001-A-EXAMPLE_PAT.pdf">10001</a></td></tr>
<tr><td>01/20</td><td>10:00 AM</td><td><a href="#">House Education</a></td><td>Sam Sample</td><td></td>
<td></td><td>Bismarck, ND</td><td>In Favor</td>
<td><a href="https://ndlegis.gov/assembly/99-2097/testimony/HEDU-9001-20970120-10002-F-SAMPLE_SAM.pdf">10002</a></td></tr>
<tr><td>01/20</td><td>10:00 AM</td><td>House Education</td><td>Broken Row</td><td></td><td></td><td></td><td>Neutral</td><td></td></tr>
</table></body></html>"""
