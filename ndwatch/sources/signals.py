"""Readers for official sources beyond bills: interim committees, agency rule
hearings and ballot measures, plus the advocacy-tracker lists used only as a
cross-check.

Every page is untrusted input. These functions only pull out plain text and
links; nothing on a page is ever followed as an instruction, and text is
escaped before it is shown.
"""

from __future__ import annotations

import base64
import html as htmllib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ndwatch.config import BASE_URL, LEGISLATURE_TZ


def interim_index_url(year: str) -> str:
    return f"{BASE_URL}/assembly/{year}/committees/interim"


AGENCY_HEARINGS_RSS = f"{BASE_URL}/events/agency-hearings"
SOS_MEASURES_URL = "https://www.sos.nd.gov/elections/voter/ballot-measures/measures-ballot"
SOS_PETITIONS_URL = "https://www.sos.nd.gov/elections/voter/ballot-measures/petitions-circulation"


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _main(soup: BeautifulSoup) -> Tag:
    return soup.find("main") or soup.body or soup


# ---------------------------------------------------------------- dates

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_MEETING_RX = re.compile(
    rf"({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})(?:\s*-\s*(\d{{1,2}}):(\d{{2}})\s*(am|pm))?", re.I
)


def parse_local_datetime(text: str) -> tuple[datetime | None, bool]:
    """'September 9, 2026 - 9:00 am to 3:15 pm CDT' -> (UTC naive start, date_only)."""
    m = _MEETING_RX.search(text or "")
    if not m:
        return None, False
    month = datetime.strptime(m.group(1), "%B").month
    day, year = int(m.group(2)), int(m.group(3))
    if m.group(4):
        hour = int(m.group(4)) % 12 + (12 if m.group(6).lower() == "pm" else 0)
        local = datetime(year, month, day, hour, int(m.group(5)), tzinfo=LEGISLATURE_TZ)
        return _to_utc(local), False
    return _to_utc(datetime(year, month, day, tzinfo=LEGISLATURE_TZ)), True


def _to_utc(local: datetime) -> datetime:
    return local.astimezone(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------- interim committees


@dataclass
class Doc:
    title: str
    url: str
    number: str | None = None  # LC number such as 27.0221.01000


@dataclass
class Meeting:
    label: str
    starts_at: datetime | None
    date_only: bool
    notice: str | None = None
    agenda: str | None = None
    minutes: str | None = None


@dataclass
class Study:
    reference: str | None  # e.g. "1119 § 1" (the bill section that assigned it)
    reference_url: str | None
    text: str


@dataclass
class CommitteePage:
    name: str
    url: str
    studies: list[Study] = field(default_factory=list)
    meetings: list[Meeting] = field(default_factory=list)
    drafts: list[Doc] = field(default_factory=list)
    memos: list[Doc] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_interim_index(page_html: str, page_url: str) -> list[tuple[str, str]]:
    """List of (committee name, absolute URL) from the interim committees page."""
    soup = BeautifulSoup(page_html, "lxml")
    m = re.search(r"/assembly/([^/]+)/committees/interim", page_url)
    prefix = f"/assembly/{m.group(1)}/committees/interim/" if m else "/committees/interim/"
    seen: dict[str, str] = {}
    for a in _main(soup).find_all("a", href=True):
        href = a["href"]
        path = re.sub(r"^https?://[^/]+", "", href)
        if path.startswith(prefix) and len(path) > len(prefix):
            url = urljoin(page_url, href)
            seen.setdefault(url, _clean(a.get_text(" ")))
    return [(name, url) for url, name in seen.items() if name]


_LC_RX = re.compile(r"\b(\d{2}\.\d{4}\.\d{5})\b")


def parse_interim_committee(page_html: str, page_url: str) -> CommitteePage:
    soup = BeautifulSoup(page_html, "lxml")
    main = _main(soup)
    title = soup.find("h1")
    name = _clean(title.get_text(" ")) if title else ""
    if not name:
        crumbs = [_clean(li.get_text(" ")) for li in soup.select("nav li, .breadcrumb li")]
        name = crumbs[-1] if crumbs else page_url.rsplit("/", 1)[-1]
    page = CommitteePage(name=name, url=page_url)

    # Studies and assignments: one paragraph each, usually "(<a>1119 § 1</a>) Study ...".
    box = main.select_one(".field--name-field-cmte-studies-assignments .field__item")
    if box is None:
        page.warnings.append("No studies section found")
    else:
        for p in box.find_all(["p", "li"]):
            text = _clean(p.get_text(" "))
            if len(text) < 25:  # headings such as "Studies"
                continue
            a = p.find("a", href=True)
            ref = _clean(a.get_text(" ")) if a else None
            ref_url = urljoin(page_url, a["href"]) if a else None
            text = re.sub(r"^\(\s*" + re.escape(ref) + r"\s*\)\s*", "", text) if ref else text
            page.studies.append(Study(reference=ref, reference_url=ref_url, text=text))

    # Meetings and their documents appear in document order inside accordions.
    current: Meeting | None = None
    seen_docs: set[str] = set()
    for el in main.descendants:
        if not isinstance(el, Tag):
            continue
        if el.name == "button" and "ac-trigger" in (el.get("class") or []):
            label = _clean(el.get("aria-label") or el.get_text(" "))
            starts, date_only = parse_local_datetime(label)
            if starts is not None:
                current = Meeting(label=label, starts_at=starts, date_only=date_only)
                page.meetings.append(current)
            continue
        if el.name != "a" or not el.get("href"):
            continue
        href = urljoin(page_url, el["href"])
        text = _clean(el.get_text(" "))
        if href in seen_docs:
            continue
        if current is not None and re.search(r"meeting-(notice|agenda|minutes)\.pdf$", href):
            kind = re.search(r"meeting-(notice|agenda|minutes)\.pdf$", href).group(1)
            setattr(current, kind, href)
            seen_docs.add(href)
        elif "/committee-memorandum/" in href and href.endswith(".pdf"):
            lc = _LC_RX.search(href)
            page.memos.append(Doc(title=text or href, url=href, number=lc.group(1) if lc else None))
            seen_docs.add(href)
        elif re.search(r"/pdf/committees/[^/]+/\d{2}\.\d{4}\.\d{5}\.pdf$", href):
            lc = _LC_RX.search(href)
            title_txt = re.sub(r"^\d{2}\.\d{4}\.\d{5}\s*-\s*", "", text)
            page.drafts.append(Doc(title=title_txt or text, url=href, number=lc.group(1) if lc else None))
            seen_docs.add(href)
    if not page.meetings:
        page.warnings.append("No meetings found")
    return page


# ---------------------------------------------------------------- agency rule hearings


@dataclass
class RssItem:
    title: str
    link: str
    published: str | None
    description: str


def parse_agency_rss(xml: str) -> list[RssItem]:
    soup = BeautifulSoup(xml, "xml")
    out = []
    for item in soup.find_all("item"):
        link = _clean(item.link.get_text()) if item.link else ""
        if not link.startswith(BASE_URL):
            continue  # only official links
        out.append(
            RssItem(
                title=_clean(item.title.get_text()) if item.title else "",
                link=link,
                published=_clean(item.pubDate.get_text()) if item.pubDate else None,
                description=_clean(BeautifulSoup(item.description.get_text(), "lxml").get_text(" "))
                if item.description else "",
            )
        )
    return out


@dataclass
class AgencyHearing:
    agency: str
    url: str
    starts_at: datetime | None  # UTC
    when_text: str
    location: str
    notice_url: str | None
    changes_url: str | None


def parse_agency_event(page_html: str, page_url: str) -> AgencyHearing:
    soup = BeautifulSoup(page_html, "lxml")
    main = _main(soup)
    title = main.select_one(".field--name-title") or soup.find("h1")
    when = main.select_one(".field--name-field-event-date2")
    when_text = _clean(when.get_text(" ")).replace("Download event to calendar", "").strip() if when else ""
    loc = main.select_one(".field--name-field-event-location")
    starts = None
    # The page carries an iCalendar file with the start time in UTC; it is the
    # least ambiguous source of the time.
    for a in main.find_all("a", href=True):
        if a["href"].startswith("data:text/calendar"):
            try:
                ics = base64.b64decode(a["href"].split(",", 1)[1]).decode("utf-8", "replace")
                m = re.search(r"DTSTART:(\d{8}T\d{6})Z", ics)
                if m:
                    starts = datetime.strptime(m.group(1), "%Y%m%dT%H%M%S")
            except (ValueError, IndexError):
                pass
    if starts is None and when_text:
        starts, _ = parse_local_datetime(when_text.replace(" PM", " pm").replace(" AM", " am"))
    notice = changes = None
    for a in main.find_all("a", href=True):
        href = urljoin(page_url, a["href"])
        if "/rule-changes/notices/" in href:
            notice = notice or href
        elif "/rule-changes/changes/" in href:
            changes = changes or href
    return AgencyHearing(
        agency=_clean(title.get_text(" ")) if title else "",
        url=page_url,
        starts_at=starts,
        when_text=when_text,
        location=_clean(loc.get_text(" ")) if loc else "",
        notice_url=notice,
        changes_url=changes,
    )


# ---------------------------------------------------------------- ballot measures


@dataclass
class BallotMeasure:
    election: str | None
    name: str
    description: str
    documents: dict[str, str]
    page_url: str
    kind: str = "on_ballot"  # on_ballot | petition


def parse_ballot_measures(page_html: str, page_url: str, kind: str = "on_ballot") -> list[BallotMeasure]:
    """Measures on the Secretary of State pages: a heading per measure, a description, document links."""
    soup = BeautifulSoup(page_html, "lxml")
    main = _main(soup)
    body = main.select_one(".field--name-body") or main
    out: list[BallotMeasure] = []
    election = None
    cur: BallotMeasure | None = None
    for el in body.find_all(["h2", "h3", "h4", "p", "a", "li", "strong"]):
        text = _clean(el.get_text(" "))
        if not text:
            continue
        if el.name in ("h2",) and re.search(r"election|\b20\d\d\b", text, re.I):
            election = text
            continue
        is_heading = el.name in ("h3", "h4") or (
            el.name == "strong" and re.match(r"(constitutional|initiated|referr?al|referendum)\s+measure", text, re.I)
        )
        if is_heading and re.search(r"measure|petition|initiat|referend", text, re.I):
            if cur is not None and cur.name == text:
                continue  # same heading marked up twice (e.g. <h3><strong>)
            cur = BallotMeasure(election=election, name=text, description="", documents={}, page_url=page_url,
                                kind=kind)
            out.append(cur)
            continue
        if cur is None:
            continue
        if el.name == "a" and el.get("href"):
            href = urljoin(page_url, el["href"])
            if href.startswith(("https://www.sos.nd.gov", "https://sos.nd.gov", BASE_URL)):
                cur.documents.setdefault(text[:80], href)
        elif el.name == "p" and not cur.description and len(text) > 30:
            cur.description = text
    # Section headings ("Initiated Measure Petitions" followed by "None at this time.") are not measures.
    return [m for m in out if m.documents or (len(m.description) > 30 and "none at this time" not in m.description.lower())]


# ---------------------------------------------------------------- tracker cross-check


@dataclass
class TrackerBill:
    tracker: str
    number: str  # normalized, e.g. "HB1144"
    title: str
    url: str


def normalize_bill_number(raw: str) -> str | None:
    """'H.B. 1144', 'HB 1144', 'SCR4010' -> 'HB1144' / 'SCR4010'."""
    m = re.match(r"^\s*([HS])\.?\s*(C\.?\s*)?([BRM])\.?\s*(\d{3,4})\s*$", raw or "", re.I)
    if not m:
        return None
    return f"{m.group(1)}{'C' if m.group(2) else ''}{m.group(3)}{m.group(4)}".upper()


def parse_tlt(page_html: str, page_url: str) -> list[TrackerBill]:
    """translegislation.com state page: the bill list is embedded as JSON."""
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page_html, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        bills = data["props"]["pageProps"]["bills"]
    except (ValueError, KeyError, TypeError):
        return []
    out = []
    for b in bills:
        num = normalize_bill_number(str(b.get("bill_number") or ""))
        if num:
            out.append(TrackerBill("Trans Legislation Tracker", num, _clean(str(b.get("title") or ""))[:300], page_url))
    return out


def parse_aclu(page_html: str, page_url: str, state: str = "ND") -> list[TrackerBill]:
    """ACLU legislative tracker: entries are embedded as (HTML-escaped) JSON for all states."""
    text = htmllib.unescape(page_html)
    out, seen = [], set()
    for m in re.finditer(r'"name":"([^"]{3,20})","state":\{"value":"' + re.escape(state) + '"', text):
        num = normalize_bill_number(m.group(1))
        if num and num not in seen:
            seen.add(num)
            out.append(TrackerBill("ACLU legislative tracker", num, "", page_url))
    return out
