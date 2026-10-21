"""Supplemental collectors for official information the JSON API does not provide.

- Bill text: the API links each version's PDF; we extract its text once.
- Testimony: listed on each bill's "Testimony" page (HTML table).
- Testimony rules: stated on the public committee hearing schedule page.

Pages are treated as untrusted input: we only read table cells and links,
never follow instructions found in the content, and keep text as plain strings.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ndwatch.config import BASE_URL

PUBLIC_SCHEDULE_URL = "https://www.ndlegis.gov/legend/committee/hearings/public-schedule/"
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_TEXT_CHARS = 800_000


# ------------------------------------------------------------------ bill text


@dataclass
class PdfText:
    ok: bool
    text: str | None
    pages: int = 0
    error: str | None = None


def extract_pdf_text(content: bytes) -> PdfText:
    if len(content) > MAX_PDF_BYTES:
        return PdfText(False, None, error="PDF too large")
    if not content.startswith(b"%PDF"):
        return PdfText(False, None, error="not a PDF")
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        parts = []
        for page in reader.pages[:400]:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts)
    except Exception as exc:  # pypdf raises many types on damaged files
        return PdfText(False, None, error=f"{type(exc).__name__}: {str(exc)[:200]}")
    if not text.strip():
        return PdfText(False, None, pages=len(parts), error="no extractable text (scanned?)")
    return PdfText(True, text[:MAX_TEXT_CHARS], pages=len(parts))


# ------------------------------------------------------------------ testimony


@dataclass
class TestimonyRow:
    document_number: str
    hearing_date: str | None
    hearing_time: str | None
    committee: str | None
    submitter: str | None
    organization: str | None
    role: str | None
    city_state: str | None
    position: str | None
    document_url: str | None


_HEADER_MAP = {
    "hearing date": "hearing_date",
    "date": "hearing_date",
    "time": "hearing_time",
    "committee": "committee",
    "name": "submitter",
    "organization": "organization",
    "role": "role",
    "city | state": "city_state",
    "city|state": "city_state",
    "city": "city_state",
    "position": "position",
    "document number": "document_number",
    "document": "document_number",
}

POSITION_LABELS = {"in favor", "in opposition", "neutral"}


def _clean(s: str | None) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def parse_testimony_page(html: str, page_url: str) -> tuple[list[TestimonyRow], list[str]]:
    """Returns (rows, warnings). Rows without a document link are skipped with a warning."""
    soup = BeautifulSoup(html, "lxml")
    rows: list[TestimonyRow] = []
    warnings: list[str] = []
    for table in soup.find_all("table"):
        headers = [_clean(th.get_text(" ")) or "" for th in table.find_all("th")]
        cols = [_HEADER_MAP.get(h.lower()) for h in headers]
        if "position" not in cols or "document_number" not in cols:
            continue
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            values: dict[str, str | None] = {}
            link = None
            for key, td in zip(cols, tds, strict=False):
                if key is None:
                    continue
                values[key] = _clean(td.get_text(" "))
                a = td.find("a", href=True)
                if key == "document_number" and a:
                    link = urljoin(page_url, a["href"])
            if link is None:
                a = tr.find("a", href=re.compile(r"/testimony/.*\.pdf$", re.I))
                link = urljoin(page_url, a["href"]) if a else None
            doc = values.get("document_number")
            if not doc and link:
                m = re.search(r"-(\d{3,})-[A-Z]-", link)
                doc = m.group(1) if m else None
            if not doc or not link:
                warnings.append(f"skipped a testimony row without a document link: {list(values.values())[:4]}")
                continue
            position = values.get("position")
            if position and position.lower() not in POSITION_LABELS:
                warnings.append(f"unrecognized position label kept verbatim: {position!r}")
            rows.append(
                TestimonyRow(
                    document_number=doc,
                    hearing_date=values.get("hearing_date"),
                    hearing_time=values.get("hearing_time"),
                    committee=values.get("committee"),
                    submitter=values.get("submitter"),
                    organization=values.get("organization"),
                    role=values.get("role"),
                    city_state=values.get("city_state"),
                    position=position,
                    document_url=link,
                )
            )
    # Deduplicate by document number (the page sometimes repeats rows).
    unique: dict[str, TestimonyRow] = {}
    for r in rows:
        unique.setdefault(r.document_number, r)
    return list(unique.values()), warnings


# ------------------------------------------------------------------ schedule rules


@dataclass
class ScheduleRules:
    deadline_rule: str | None
    work_session_note: str | None
    how_to_submit_url: str | None
    submit_url: str | None
    covered_dates: str | None


def parse_public_schedule(html: str, page_url: str = PUBLIC_SCHEDULE_URL) -> ScheduleRules:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" "))
    sentences = re.split(r"(?<=[.!?])\s+", text)
    deadline = next(
        (s.strip() for s in sentences if re.search(r"deadline", s, re.I) and re.search(r"testimony", s, re.I)),
        None,
    )
    work = next(
        (s.strip() for s in sentences if re.search(r"work session", s, re.I) and re.search(r"testimony", s, re.I)),
        None,
    )
    how = None
    submit = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        label = (a.get_text(" ") or "").lower()
        if how is None and re.search(r"testimony", href, re.I) and href.lower().endswith(".pdf"):
            how = urljoin(page_url, href)
        if submit is None and "submit" in label and "testimony" in label and not href.lower().endswith(".pdf"):
            submit = urljoin(page_url, href)
    covered = None
    m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4}) to ([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if m:
        covered = f"{m.group(1)} to {m.group(2)}"
    return ScheduleRules(
        deadline_rule=deadline[:500] if deadline else None,
        work_session_note=work[:500] if work else None,
        how_to_submit_url=how,
        submit_url=submit,
        covered_dates=covered,
    )


def testimony_page_url(bill_url: str | None) -> str | None:
    """Derive the testimony page from the overview URL (bo1144 -> bt1144), as the site does."""
    if not bill_url:
        return None
    return re.sub(r"/bill-overview/bo(\w+)\.html$", r"/bill-testimony/bt\1.html", bill_url)


def absolute(url: str) -> str:
    return urljoin(BASE_URL + "/", url)
