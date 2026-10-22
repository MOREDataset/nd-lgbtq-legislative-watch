"""Early signals: official items other than bills that can show what is coming.

- Interim committees (studies, 2027 bill drafts, memos, meeting agendas)
- Agency rule hearings (proposed changes to the ND Administrative Code)
- Ballot measures (Secretary of State)
- Advocacy-tracker lists, used only to suggest bills a reviewer should look at

All items are scored with the same topic rules as bills. Nothing here is ever
shown as a fact about a bill; tracker lists only feed the Reviewer page.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ndwatch.config import Settings
from ndwatch.db.schema import Bill, Relevance, ReviewDecision, Signal, SourceCheck
from ndwatch.events import LOW, MEDIUM
from ndwatch.ingest import EventSpec, EventWriter
from ndwatch.relevance.detector import NOT_RELEVANT, POSSIBLE, RELEVANT, classify, default_rules
from ndwatch.sources.http import Fetcher
from ndwatch.sources.pages import extract_pdf_text
from ndwatch.sources.signals import (
    AGENCY_HEARINGS_RSS,
    SOS_MEASURES_URL,
    SOS_PETITIONS_URL,
    interim_index_url,
    parse_aclu,
    parse_agency_event,
    parse_agency_rss,
    parse_ballot_measures,
    parse_interim_committee,
    parse_interim_index,
    parse_tlt,
)
from ndwatch.timeutil import fmt_date, utcnow

log = logging.getLogger(__name__)

DAILY = timedelta(hours=23)
# Meeting agendas are read only around the meeting; older ones are history.
AGENDA_WINDOW = timedelta(days=60)
KIND_LABELS = {
    "interim_study": "Interim study",
    "bill_draft": "Bill draft",
    "committee_memo": "Committee memo",
    "committee_meeting": "Committee meeting",
    "agency_rule": "Agency rule change",
    "ballot_measure": "Ballot measure",
}
TRACKER_URLS = {
    "Trans Legislation Tracker": "https://translegislation.com/bills/{year}/ND",
    "ACLU legislative tracker": "https://www.aclu.org/legislative-attacks-on-lgbtq-rights-{year}?state=ND",
}


def _h(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def _slug(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def _last_ok(db: DbSession, source: str) -> SourceCheck | None:
    return db.scalars(
        select(SourceCheck).where(SourceCheck.source == source, SourceCheck.ok.is_(True))
        .order_by(SourceCheck.checked_at.desc()).limit(1)
    ).first()


def _due(db: DbSession, source: str, every: timedelta, now: datetime) -> bool:
    last = _last_ok(db, source)
    return last is None or now - last.checked_at >= every


def _check(db: DbSession, run_id: int, source: str, fetch, error: str | None = None) -> None:
    from ndwatch.monitor import _record_check  # local import: monitor imports this module

    _record_check(db, run_id, source, fetch, error)


def upsert_signal(db: DbSession, sid: str, now: datetime, backfill: bool, **fields) -> tuple[Signal, bool]:
    row = db.get(Signal, sid)
    new = row is None
    if new:
        fields.setdefault("extra", {})
        row = Signal(id=sid, first_seen_at=now, last_seen_at=now, backfill=backfill, **fields)
        if row.doc_url and row.text_status in (None, "none"):
            row.text_status = "pending"
        db.add(row)
        return row, True
    for k, v in fields.items():
        if k == "extra":
            row.extra = {**(row.extra or {}), **(v or {})}
        elif getattr(row, k) != v:
            if k == "doc_url" and v:
                row.text_status = "pending"
            setattr(row, k, v)
    row.last_seen_at = now
    row.removed_at = None
    return row, False


# ---------------------------------------------------------------- interim committees


def _interim(db: DbSession, fetcher: Fetcher, report, year: str, now: datetime) -> None:
    index_source = f"interim-index:{year}"
    if not _due(db, index_source, DAILY, now):
        return
    first_load = _last_ok(db, index_source) is None
    url = interim_index_url(year)
    f = fetcher.get(url)
    if not f.ok:
        _check(db, report.run_id, index_source, f)
        if f.status == 404:
            report.notes.append(f"Interim committees {year}: no page yet")
        else:
            report.errors.append(f"Interim committees {year}: {f.error}")
        return
    committees = parse_interim_index(f.text, url)
    _check(db, report.run_id, index_source, f, None if committees else "no committees listed")
    if not committees:
        report.notes.append(f"Interim committees {year}: none listed yet")
        return
    counts = {"studies": 0, "drafts": 0, "memos": 0, "meetings": 0}
    for name, curl in committees:
        cf = fetcher.get(curl)
        source = f"interim:{year}:{_slug(curl)}"
        if not cf.ok:
            _check(db, report.run_id, source, cf)
            continue
        page = parse_interim_committee(cf.text, curl)
        _check(db, report.run_id, source, cf)
        body = page.name or name
        seen: set[str] = set()
        for st in page.studies:
            sid = f"study:{year}:{_slug(curl)}:{_h(st.text)}"
            seen.add(sid)
            upsert_signal(db, sid, now, first_load, kind="interim_study", body=body, assembly_id=year,
                          title=st.text[:300], detail=st.text, url=st.reference_url, page_url=curl,
                          extra={"reference": st.reference})
            counts["studies"] += 1
        for d in page.drafts:
            sid = f"draft:{d.number or _h(d.url)}"
            seen.add(sid)
            upsert_signal(db, sid, now, first_load, kind="bill_draft", body=body, assembly_id=year,
                          title=d.title[:300], url=d.url, page_url=curl, doc_url=d.url,
                          extra={"lc_number": d.number})
            counts["drafts"] += 1
        for d in page.memos:
            sid = f"memo:{d.number or _h(d.url)}"
            seen.add(sid)
            upsert_signal(db, sid, now, first_load, kind="committee_memo", body=body, assembly_id=year,
                          title=d.title[:300], url=d.url, page_url=curl, extra={"lc_number": d.number})
            counts["memos"] += 1
        for m in page.meetings:
            key = m.agenda or m.notice or f"{curl}#{m.label}"
            sid = f"meeting:{_h(key)}"
            seen.add(sid)
            recent = m.starts_at is not None and m.starts_at > now - AGENDA_WINDOW
            upsert_signal(db, sid, now, first_load, kind="committee_meeting", body=body, assembly_id=year,
                          title=f"{body} meeting", url=m.agenda or m.notice, page_url=curl,
                          event_at=m.starts_at, event_date_only=m.date_only,
                          doc_url=m.agenda if recent else None,
                          extra={"notice": m.notice, "agenda": m.agenda, "minutes": m.minutes, "when": m.label})
            counts["meetings"] += 1
        # Items that disappeared from this committee page are kept but marked.
        for row in db.scalars(select(Signal).where(Signal.page_url == curl, Signal.removed_at.is_(None))):
            if row.id not in seen and row.kind != "agency_rule":
                row.removed_at = now
        db.commit()
    report.notes.append(
        f"Interim {year}: {len(committees)} committees, {counts['studies']} studies, "
        f"{counts['drafts']} bill drafts, {counts['meetings']} meetings"
    )


# ---------------------------------------------------------------- agency rules


def _agency_rules(db: DbSession, fetcher: Fetcher, report, now: datetime, budget: int) -> int:
    source = "agency-hearings"
    first_load = _last_ok(db, source) is None
    f = fetcher.get(AGENCY_HEARINGS_RSS)
    if not f.ok:
        _check(db, report.run_id, source, f)
        report.errors.append(f"Agency rule hearings feed: {f.error}")
        return 0
    items = parse_agency_rss(f.text)
    _check(db, report.run_id, source, f, None if items else "feed had no items")
    known = {}
    for row in db.scalars(select(Signal).where(Signal.kind == "agency_rule")):
        known[row.id] = row
    fetched = 0
    for it in items:
        sid = f"rule:{it.link}"
        row = known.get(sid)
        # Read each hearing page once; retry a page that failed after a day.
        if row is not None and not ((row.extra or {}).get("page_error") and now - row.last_seen_at > DAILY):
            continue
        if fetched >= budget:
            break
        ef = fetcher.get(it.link)
        fetched += 1
        if not ef.ok:
            upsert_signal(db, sid, now, first_load, kind="agency_rule", body=it.title,
                          title=f"{it.title}: proposed rule changes", detail=it.description, url=it.link,
                          page_url=AGENCY_HEARINGS_RSS, extra={"page_error": ef.error or str(ef.status)})
            db.commit()
            continue
        h = parse_agency_event(ef.text, it.link)
        upsert_signal(
            db, sid, now, first_load, kind="agency_rule", body=h.agency or it.title, title=f"{h.agency or it.title}: proposed rule changes",
            detail=h.when_text, url=it.link, page_url=AGENCY_HEARINGS_RSS, event_at=h.starts_at,
            doc_url=h.changes_url or h.notice_url,
            extra={"notice": h.notice_url, "changes": h.changes_url, "location": h.location, "when": h.when_text,
                   "page_error": None},
        )
        db.commit()
    if fetched:
        report.notes.append(f"Agency rule hearings: {fetched} new hearing pages read")
    return fetched


# ---------------------------------------------------------------- ballot measures


def _ballot(db: DbSession, fetcher: Fetcher, report, now: datetime) -> None:
    for kind, url in (("on_ballot", SOS_MEASURES_URL), ("petition", SOS_PETITIONS_URL)):
        source = f"ballot:{kind}"
        if not _due(db, source, DAILY, now):
            continue
        first_load = _last_ok(db, source) is None
        f = fetcher.get(url)
        if not f.ok:
            _check(db, report.run_id, source, f)
            report.notes.append(f"Ballot measures ({kind}): {f.error}")
            continue
        measures = parse_ballot_measures(f.text, url, kind)
        _check(db, report.run_id, source, f)
        for m in measures:
            full = next((u for label, u in m.documents.items() if "full text" in label.lower()), None)
            pdf = full or next((u for u in m.documents.values() if u.lower().endswith(".pdf")), None)
            sid = f"ballot:{kind}:{_h((m.election or '') + m.name)}"
            upsert_signal(db, sid, now, first_load, kind="ballot_measure", body="Secretary of State",
                          title=m.name[:300], detail=m.description, url=pdf or url, page_url=url, doc_url=pdf,
                          extra={"election": m.election, "documents": m.documents, "stage": kind})
        db.commit()
        report.notes.append(f"Ballot measures ({kind}): {len(measures)} listed")


# ---------------------------------------------------------------- tracker cross-check


def _trackers(db: DbSession, fetcher: Fetcher, report, now: datetime, years: list[str]) -> None:
    for year in years:
        for tracker, template in TRACKER_URLS.items():
            url = template.format(year=year)
            source = f"tracker:{_h(tracker)}:{year}"
            if not _due(db, source, DAILY, now):
                continue
            f = fetcher.get(url)
            if not f.ok:
                _check(db, report.run_id, source, f)
                report.notes.append(f"{tracker} {year}: not available ({f.status or f.error})")
                continue
            bills = parse_tlt(f.text, url) if "translegislation" in url else parse_aclu(f.text, url)
            _check(db, report.run_id, source, f)
            for b in bills:
                sid = f"tracker:{_h(tracker)}:{year}:{b.number}"
                upsert_signal(db, sid, now, False, kind="tracker", body=tracker, title=f"{b.number} {b.title}".strip(),
                              url=url, page_url=url, extra={"number": b.number, "year": year})
            db.commit()
            report.notes.append(f"{tracker} {year}: {len(bills)} North Dakota bills listed")


def tracker_suggestions(db: DbSession) -> list[dict]:
    """Bills a tracker names that we have not listed and no reviewer has decided on."""
    flagged = set(db.scalars(select(Relevance.bill_uid).where(Relevance.status.in_([RELEVANT, POSSIBLE]))))
    decided = set(db.scalars(select(ReviewDecision.bill_uid)))
    by_bill: dict[str, dict] = {}
    for s in db.scalars(select(Signal).where(Signal.kind == "tracker", Signal.removed_at.is_(None))):
        num, year = (s.extra or {}).get("number"), (s.extra or {}).get("year")
        if not num or not year:
            continue
        bill = _find_bill(db, num, str(year))
        if bill is None or bill.uid in flagged or bill.uid in decided:
            continue
        item = by_bill.setdefault(bill.uid, {"uid": bill.uid, "name": bill.name, "summary": bill.summary or bill.title,
                                             "trackers": []})
        if s.body not in item["trackers"]:
            item["trackers"].append(s.body)
    return sorted(by_bill.values(), key=lambda x: x["uid"])


def _find_bill(db: DbSession, number: str, year: str) -> Bill | None:
    m = re.match(r"([A-Z]+)(\d+)$", number)
    if not m:
        return None
    name = f"{m.group(1)} {m.group(2)}"
    return db.scalars(
        select(Bill).where(Bill.name == name, Bill.session_id.like(f"{year}%")).order_by(Bill.session_id)
    ).first()


# ---------------------------------------------------------------- text and scoring


def _read_texts(db: DbSession, fetcher: Fetcher, report, budget: int) -> None:
    order = {"agency_rule": 0, "bill_draft": 1, "ballot_measure": 2, "committee_meeting": 3}
    pending = db.scalars(select(Signal).where(Signal.text_status == "pending", Signal.doc_url.is_not(None))).all()
    pending.sort(key=lambda s: (order.get(s.kind, 9), -(s.event_at.timestamp() if s.event_at else 0)))
    done = failed = 0
    for s in pending[:budget]:
        urls = [s.doc_url]
        if s.kind == "agency_rule":
            notice = (s.extra or {}).get("notice")
            if notice and notice != s.doc_url:
                urls.append(notice)
        parts, err = [], None
        for u in urls:
            f = fetcher.get(u)
            if not f.ok:
                err = f.error
                continue
            pdf = extract_pdf_text(f.content)
            if pdf.ok and pdf.text:
                parts.append(pdf.text)
            else:
                err = pdf.error
        if parts:
            s.text = "\n\n".join(parts)
            s.text_status = "ok"
            done += 1
        else:
            s.text_status = "failed"
            s.extra = {**(s.extra or {}), "text_error": err}
            failed += 1
        db.commit()
    if done or failed:
        report.notes.append(f"Early-signal documents: {done} read, {failed} failed")


def _score(db: DbSession, report) -> None:
    rules = default_rules()
    writer = EventWriter(db, report.run_id)
    flagged = 0
    for s in db.scalars(select(Signal).where(Signal.kind != "tracker")):
        key = _h(f"{rules.version}|{s.title}|{s.detail}|{s.text_status}|{len(s.text or '')}")
        if (s.extra or {}).get("scored") == key:
            continue
        summary = s.detail if s.kind in ("interim_study", "ballot_measure") else None
        title = s.title if s.kind not in ("committee_meeting", "agency_rule") else None
        texts = [(s.id, s.text, s.doc_url)] if s.text else []
        r = classify(title=title, summary=summary, texts=texts, rules=rules)
        was = s.status
        s.status, s.score, s.topics = r.status, r.score, r.topics
        s.evidence = [e.as_dict() for e in r.evidence[:8]]
        s.rules_version = rules.version
        s.extra = {**(s.extra or {}), "scored": key}
        if r.status in (RELEVANT, POSSIBLE) and was not in (RELEVANT, POSSIBLE) and s.removed_at is None:
            flagged += 1
            writer.emit(
                EventSpec(
                    dedupe_key=f"signal:{s.id}:flagged",
                    kind=f"signal_{s.kind}",
                    importance=MEDIUM if r.status == RELEVANT else LOW,
                    title=signal_headline(s)[:300],
                    event_date=s.event_at,
                    event_date_only=s.event_date_only,
                    source_url=s.url or s.page_url,
                    source_label=f"{KIND_LABELS.get(s.kind, 'Official item')} (official source)",
                ),
                backfill=s.backfill,
            )
    db.commit()
    report.events_created += writer.written
    if flagged:
        report.notes.append(f"Early signals: {flagged} newly flagged")


def signal_headline(s: Signal) -> str:
    when = f" ({fmt_date(s.event_at, s.event_date_only)})" if s.event_at else ""
    maybe = "may affect" if s.status == RELEVANT else "might affect"
    if s.kind == "interim_study":
        return f"The {s.body} is studying a topic that {maybe} LGBTQ+ people: {s.title[:140]}"
    if s.kind == "bill_draft":
        return f"A bill draft from the {s.body} {maybe} LGBTQ+ people: {s.title[:140]}"
    if s.kind == "committee_memo":
        return f"A {s.body} memo {maybe} LGBTQ+ people: {s.title[:140]}"
    if s.kind == "committee_meeting":
        return f"The {s.body} meeting agenda{when} mentions a topic that {maybe} LGBTQ+ people."
    if s.kind == "agency_rule":
        return f"{s.body} proposed rule changes that {maybe} LGBTQ+ people. Public hearing{when}."
    if s.kind == "ballot_measure":
        return f"A ballot measure {maybe} LGBTQ+ people: {s.title[:140]}"
    return s.title


# ---------------------------------------------------------------- entry point


def collect_signals(factory, fetcher: Fetcher, settings: Settings, report, assemblies: list[str]) -> None:
    """One pass over every early-signal source. Each part fails on its own."""
    if not settings.signals_enabled:
        return
    now = utcnow()
    budget = settings.max_signal_docs_per_run
    parts = [
        ("interim", lambda db: [_interim(db, fetcher, report, y, now) for y in assemblies]),
        ("agency rules", lambda db: _agency_rules(db, fetcher, report, now, budget)),
        ("ballot measures", lambda db: _ballot(db, fetcher, report, now)),
        ("trackers", lambda db: _trackers(db, fetcher, report, now, sorted({a.split("-")[-1] for a in assemblies}))),
        ("documents", lambda db: _read_texts(db, fetcher, report, budget)),
        ("scoring", lambda db: _score(db, report)),
    ]
    for label, fn in parts:
        with factory() as db:
            try:
                fn(db)
                db.commit()
            except Exception as exc:  # one broken page must not stop the rest
                db.rollback()
                report.errors.append(f"Early signals ({label}): {type(exc).__name__}: {exc}")
                log.exception("early signals %s failed", label)


__all__ = ["collect_signals", "tracker_suggestions", "signal_headline", "KIND_LABELS", "NOT_RELEVANT"]
