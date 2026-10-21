"""One monitoring cycle: read official sources, store them, detect changes.

Run it with `ndwatch monitor` (GitHub Actions does this on a schedule). It is
safe to run repeatedly: unchanged sources are recognized by their content hash
and produce no new events.
"""

from __future__ import annotations

import hashlib
import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import selectinload, sessionmaker

from ndwatch.config import Settings
from ndwatch.db.schema import (
    Assembly,
    Bill,
    BillVersion,
    Hearing,
    MonitorRun,
    Relevance,
    ReviewDecision,
    Session,
    SourceCheck,
    SourceFact,
    Testimony,
    TestimonyCheck,
)
from ndwatch.events import HIGH, LOW
from ndwatch.ingest import (
    EventSpec,
    EventWriter,
    upsert_assembly,
    upsert_bill,
    upsert_members,
    upsert_roll_calls,
    upsert_session,
)
from ndwatch.relevance.detector import RELEVANT, classify, default_rules
from ndwatch.sources.api import LegislativeApi
from ndwatch.sources.http import Fetcher, FetchResult
from ndwatch.sources.pages import (
    PUBLIC_SCHEDULE_URL,
    extract_pdf_text,
    parse_public_schedule,
    parse_testimony_page,
    testimony_page_url,
)
from ndwatch.timeutil import local_to_utc, utcnow

log = logging.getLogger("ndwatch.monitor")

MODE_ACTIVE, MODE_PREFILING, MODE_OFF = "active", "prefiling", "off_season"
HISTORICAL_REFRESH = timedelta(hours=24)


@dataclass
class CycleReport:
    run_id: int
    status: str
    mode: str | None
    events_created: int = 0
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- policy


def current_mode(db: DbSession, now: datetime | None = None) -> str:
    now = now or utcnow()
    today = now.date()
    sessions = db.scalars(select(Session)).all()
    latest_action = db.scalar(select(func.max(Bill.last_action_date)))
    recent_activity = latest_action is not None and (now - latest_action) < timedelta(days=21)
    for s in sessions:
        if s.current and s.start and s.start <= today and recent_activity:
            return MODE_ACTIVE
    for s in sessions:
        if s.start and today < s.start <= today + timedelta(days=90):
            return MODE_PREFILING
    if recent_activity:
        return MODE_ACTIVE
    return MODE_OFF


def interval_for(mode: str, settings: Settings) -> int:
    p = settings.polling
    return {MODE_ACTIVE: p.active_session, MODE_PREFILING: p.prefiling}.get(mode, p.off_season)


def last_ok_run(db: DbSession) -> MonitorRun | None:
    return db.scalars(
        select(MonitorRun).where(MonitorRun.status.in_(["ok", "partial"])).order_by(MonitorRun.started_at.desc()).limit(1)
    ).first()


def is_due(db: DbSession, settings: Settings, now: datetime | None = None) -> tuple[bool, str, int]:
    now = now or utcnow()
    mode = current_mode(db, now)
    minutes = interval_for(mode, settings)
    last = last_ok_run(db)
    if last is None:
        return True, mode, minutes
    due = (now - last.started_at) >= timedelta(minutes=minutes - settings.polling.slack)
    return due, mode, minutes


# ---------------------------------------------------------------- helpers


def _record_check(
    db: DbSession, run_id: int, source: str, fetch: FetchResult, error: str | None = None,
    source_last_updated: datetime | None = None,
) -> SourceCheck:
    prev = db.scalars(
        select(SourceCheck).where(SourceCheck.source == source, SourceCheck.ok.is_(True))
        .order_by(SourceCheck.checked_at.desc()).limit(1)
    ).first()
    sha = fetch.sha256 if fetch.ok else None
    ok = fetch.ok and error is None
    check = SourceCheck(
        run_id=run_id, source=source, url=fetch.url, checked_at=fetch.fetched_at.replace(tzinfo=None),
        ok=ok, http_status=fetch.status, error=error or fetch.error,
        source_last_updated=local_to_utc(source_last_updated), content_sha256=sha,
        changed=None if not ok else (prev is None or prev.content_sha256 != sha),
    )
    db.add(check)
    return check


def _unchanged_since_last_ok(db: DbSession, source: str, sha: str) -> bool:
    prev = db.scalars(
        select(SourceCheck).where(SourceCheck.source == source, SourceCheck.ok.is_(True))
        .order_by(SourceCheck.checked_at.desc()).limit(1)
    ).first()
    return prev is not None and prev.content_sha256 == sha


def _last_ok_check(db: DbSession, source: str) -> SourceCheck | None:
    return db.scalars(
        select(SourceCheck).where(SourceCheck.source == source, SourceCheck.ok.is_(True))
        .order_by(SourceCheck.checked_at.desc()).limit(1)
    ).first()


def set_fact(db: DbSession, key: str, value: str | None, url: str, now: datetime) -> None:
    if not value:
        return
    row = db.get(SourceFact, key)
    if row is None:
        db.add(SourceFact(key=key, value=value, source_url=url, checked_at=now, first_seen_at=now))
    else:
        if row.value != value:
            row.first_seen_at = now
        row.value, row.source_url, row.checked_at = value, url, now


# ---------------------------------------------------------------- the cycle


def run_cycle(
    factory: sessionmaker[DbSession],
    fetcher: Fetcher,
    settings: Settings,
    trigger: str = "manual",
    force: bool = False,
    only_assemblies: list[str] | None = None,
) -> CycleReport:
    now = utcnow()
    with factory() as db:
        due, mode, minutes = is_due(db, settings, now)
        run = MonitorRun(started_at=now, status="running", mode=mode, trigger=trigger, notes=[], errors=[])
        db.add(run)
        db.commit()
        run_id = run.id
        if not due and not force:
            run.status = "skipped"
            run.finished_at = utcnow()
            run.notes = [f"Not due: mode {mode} checks every {minutes} min."]
            db.commit()
            return CycleReport(run_id, "skipped", mode, notes=run.notes)

    report = CycleReport(run_id, "ok", mode)
    api = LegislativeApi(fetcher)
    try:
        _cycle_body(factory, api, fetcher, settings, report, only_assemblies)
    except Exception as exc:  # never leave a run "running"
        report.errors.append(f"Unexpected error: {type(exc).__name__}: {exc}")
        log.error(traceback.format_exc())
    with factory() as db:
        run = db.get(MonitorRun, run_id)
        run.finished_at = utcnow()
        run.events_created = report.events_created
        run.notes = report.notes
        run.errors = report.errors
        run.requests_made = getattr(fetcher, "request_count", 0)
        if report.errors and report.status != "failed":
            report.status = "partial"
        run.status = report.status
        run.mode = current_mode(db)
        db.commit()
    return report


def _cycle_body(factory, api: LegislativeApi, fetcher: Fetcher, settings: Settings, report: CycleReport,
                only_assemblies: list[str] | None) -> None:
    run_id = report.run_id

    # 1. Discover assemblies and sessions (never hardcoded).
    with factory() as db:
        parsed = api.assemblies()
        _record_check(db, run_id, "assemblies", parsed.fetch, parsed.error)
        if not parsed.ok:
            report.errors.append(f"Assembly list unavailable: {parsed.error}")
            db.commit()
            known = [a.id for a in db.scalars(select(Assembly).order_by(Assembly.number.desc()))]
            if not known:
                report.status = "failed"
                return
            targets = only_assemblies or known[: max(1, settings.assemblies_to_track)]
        else:
            for a in parsed.data:
                upsert_assembly(db, a)
            db.commit()
            ordered = sorted((a for a in parsed.data if a.year), key=lambda a: -(a.assembly or 0))
            targets = [a.year for a in ordered[: max(1, settings.assemblies_to_track)]]
            # Always include any assembly that has a session marked current.
            targets += [a.year for a in ordered if any(s.current for s in a.sessions) and a.year not in targets]
            targets += [y for y in settings.extra_assemblies if y not in targets]
            if only_assemblies:
                targets = only_assemblies
        db.commit()
    report.notes.append(f"Assemblies checked: {', '.join(targets)}")

    for year in targets:
        _ingest_assembly(factory, api, settings, report, year)

    _collect_schedule_rules(factory, fetcher, report)
    _collect_bill_text(factory, fetcher, settings, report)
    _update_relevance(factory, report)
    _collect_testimony(factory, fetcher, settings, report)


def _ingest_assembly(factory, api: LegislativeApi, settings: Settings, report: CycleReport, year: str) -> None:
    run_id = report.run_id
    with factory() as db:
        has_current = db.scalar(
            select(func.count()).select_from(Session).where(Session.assembly_id == year, Session.current.is_(True))
        )
        newest = db.scalar(select(Assembly.id).order_by(Assembly.number.desc()).limit(1))
        last = _last_ok_check(db, f"bills:{year}")
        historical = not has_current and year != newest
        if historical and last and (utcnow() - last.checked_at) < HISTORICAL_REFRESH:
            report.notes.append(f"{year}: historical assembly, checked {last.checked_at:%Y-%m-%d %H:%M} UTC; skipping")
            return

    # Sessions
    with factory() as db:
        p = api.sessions(year)
        _record_check(db, run_id, f"sessions:{year}", p.fetch, p.error, p.data.last_updated if p.ok else None)
        if p.ok:
            for s in p.data.sessions:
                upsert_session(db, year, s)
        else:
            report.errors.append(f"{year} sessions: {p.error}")
        db.commit()

    # Members (sponsor details: party, district, profile link)
    with factory() as db:
        p = api.members(year)
        _record_check(db, run_id, f"members:{year}", p.fetch, p.error, p.data.last_updated if p.ok else None)
        if p.ok and not _unchanged_since_last_ok_before(db, f"members:{year}", p.fetch):
            upsert_members(db, year, p.data.members)
        elif not p.ok:
            report.errors.append(f"{year} members: {p.error}")
        db.commit()

    # Bills
    with factory() as db:
        p = api.bills(year)
        report.notes.extend(f"{year}: {w}" for w in p.warnings)
        if not p.ok:
            _record_check(db, run_id, f"bills:{year}", p.fetch, p.error)
            # A brand-new assembly may not have a bills file yet; that is not an error.
            if p.fetch.status == 404:
                report.notes.append(f"{year}: no bills published yet")
            else:
                report.errors.append(f"{year} bills: {p.error}")
            db.commit()
            return
        unchanged = _unchanged_since_last_ok(db, f"bills:{year}", p.fetch.sha256)
        _record_check(db, run_id, f"bills:{year}", p.fetch, None, p.data.last_updated)
        db.commit()
        bills = p.data.bill_list()
        if not bills:
            report.notes.append(f"{year}: bills file has no bills yet")
        if unchanged:
            report.notes.append(f"{year}: bills unchanged since last check")
        else:
            first_load = not db.scalar(select(func.count()).select_from(Bill).where(Bill.assembly_id == year))
            writer = EventWriter(db, run_id, backfill=first_load)
            writer.preload()
            # Load this assembly's bills with their child rows in a few queries.
            db.scalars(
                select(Bill).where(Bill.assembly_id == year).options(
                    selectinload(Bill.sponsors), selectinload(Bill.actions),
                    selectinload(Bill.versions), selectinload(Bill.hearings),
                )
            ).all()
            new = changed = 0
            sessions = {s.id: s.name for s in db.scalars(select(Session).where(Session.assembly_id == year))}
            for i, b in enumerate(bills):
                try:
                    _, is_new, did_change = upsert_bill(db, year, b, writer, run_id, sessions.get(b.session_id or ""))
                    new += is_new
                    changed += did_change and not is_new
                except Exception as exc:
                    db.rollback()
                    report.errors.append(f"{year} {b.name}: {type(exc).__name__}: {exc}")
                if i % 200 == 199:
                    db.commit()
            db.commit()
            report.events_created += writer.written
            report.notes.append(
                f"{year}: {len(bills)} bills, {new} new, {changed} updated"
                + (" (first load: history recorded quietly)" if first_load else "")
            )

    # Roll calls (individual legislator votes)
    with factory() as db:
        p = api.roll_calls(year)
        if not p.ok:
            _record_check(db, run_id, f"roll_call:{year}", p.fetch, p.error)
            if p.fetch.status != 404:
                report.errors.append(f"{year} roll calls: {p.error}")
        else:
            unchanged = _unchanged_since_last_ok(db, f"roll_call:{year}", p.fetch.sha256)
            _record_check(db, run_id, f"roll_call:{year}", p.fetch, None, p.data.last_updated)
            if not unchanged:
                n = upsert_roll_calls(db, p.data.roll_call)
                report.notes.append(f"{year}: {n} roll calls stored or completed")
        db.commit()


def _unchanged_since_last_ok_before(db: DbSession, source: str, fetch: FetchResult) -> bool:
    """Like _unchanged_since_last_ok, but ignores the check we just added in this session."""
    rows = db.scalars(
        select(SourceCheck).where(SourceCheck.source == source, SourceCheck.ok.is_(True))
        .order_by(SourceCheck.checked_at.desc()).limit(2)
    ).all()
    return len(rows) == 2 and rows[1].content_sha256 == fetch.sha256


def _collect_schedule_rules(factory, fetcher: Fetcher, report: CycleReport) -> None:
    with factory() as db:
        f = fetcher.get(PUBLIC_SCHEDULE_URL)
        if not f.ok:
            _record_check(db, report.run_id, "public_schedule", f)
            report.errors.append(f"Hearing schedule page unavailable: {f.error}")
            db.commit()
            return
        try:
            rules = parse_public_schedule(f.text, PUBLIC_SCHEDULE_URL)
        except Exception as exc:
            _record_check(db, report.run_id, "public_schedule", f, f"parse error: {exc}")
            report.errors.append(f"Hearing schedule page could not be read: {exc}")
            db.commit()
            return
        _record_check(db, report.run_id, "public_schedule", f)
        now = utcnow()
        set_fact(db, "testimony_deadline_rule", rules.deadline_rule, PUBLIC_SCHEDULE_URL, now)
        set_fact(db, "work_session_testimony_note", rules.work_session_note, PUBLIC_SCHEDULE_URL, now)
        set_fact(db, "how_to_submit_testimony_url", rules.how_to_submit_url, PUBLIC_SCHEDULE_URL, now)
        set_fact(db, "submit_testimony_url", rules.submit_url, PUBLIC_SCHEDULE_URL, now)
        set_fact(db, "public_schedule_dates", rules.covered_dates, PUBLIC_SCHEDULE_URL, now)
        if not rules.deadline_rule:
            report.notes.append("Hearing schedule page did not state a testimony deadline this time.")
        db.commit()


def _relevant_uids(db: DbSession) -> set[str]:
    auto = set(db.scalars(select(Relevance.bill_uid).where(Relevance.status == RELEVANT)))
    latest: dict[str, str] = {}
    for d in db.scalars(select(ReviewDecision).order_by(ReviewDecision.created_at)):
        latest[d.bill_uid] = d.decision
    included = {u for u, d in latest.items() if d == "include"}
    excluded = {u for u, d in latest.items() if d == "exclude"}
    return (auto | included) - excluded


def _collect_bill_text(factory, fetcher: Fetcher, settings: Settings, report: CycleReport) -> None:
    budget = settings.max_pdfs_per_run
    if budget <= 0:
        return
    with factory() as db:
        current_sessions = set(db.scalars(select(Session.id).where(Session.current.is_(True))))
        relevant = _relevant_uids(db)
        pending = db.execute(
            select(BillVersion, Bill.session_id, Bill.uid)
            .join(Bill, Bill.uid == BillVersion.bill_uid)
            .where(BillVersion.text_status == "pending", BillVersion.document_url.is_not(None))
        ).all()
        # Priority: bills already flagged, then live sessions, then newest assemblies first.
        pending.sort(
            key=lambda r: (r[2] not in relevant, r[1] not in current_sessions, -int(r[1] or 0), r[0].position)
        )
        fetched = failed = 0
        for version, _sid, _uid in pending[:budget]:
            f = fetcher.get(version.document_url)
            version.text_fetched_at = utcnow()
            if not f.ok:
                failed += 1
                version.text_error = (f.error or "fetch failed")[:300]
                # Leave as pending so a later run retries temporary failures; give up on 404.
                if f.status == 404:
                    version.text_status = "failed"
                continue
            pdf = extract_pdf_text(f.content)
            if pdf.ok:
                version.text = pdf.text
                version.text_status = "ok"
                version.text_sha256 = hashlib.sha256(pdf.text.encode()).hexdigest()
                version.text_error = None
                fetched += 1
            else:
                version.text_status = "failed"
                version.text_error = pdf.error
                failed += 1
            db.commit()
        db.commit()
        left = max(0, len(pending) - budget)
        if pending:
            report.notes.append(f"Bill text: {fetched} versions read, {failed} failed, {left} waiting for later runs")


def _update_relevance(factory, report: CycleReport) -> None:
    rules = default_rules()
    with factory() as db:
        writer = EventWriter(db, report.run_id)
        bills = db.scalars(select(Bill).options(selectinload(Bill.versions))).all()
        existing = {r.bill_uid: r for r in db.scalars(select(Relevance))}
        updated = newly = 0
        for bill in bills:
            ok_versions = [v for v in bill.versions if v.text_status == "ok" and v.text]
            used = sorted(v.lc_number for v in ok_versions)
            cur = existing.get(bill.uid)
            if (
                cur is not None
                and cur.rules_version == rules.version
                and sorted(cur.text_versions_used or []) == used
                and cur.computed_at >= bill.last_changed_at
            ):
                continue
            result = classify(
                title=bill.title,
                summary=bill.summary,
                texts=[(v.lc_number, v.text, v.document_url) for v in ok_versions],
                rules=rules,
            )
            was = cur.status if cur else None
            if cur is None:
                cur = Relevance(bill_uid=bill.uid)
                db.add(cur)
            cur.status = result.status
            cur.level = result.level
            cur.score = result.score
            cur.topics = result.topics
            cur.evidence = [e.as_dict() for e in result.evidence[:12]]
            cur.rules_version = result.rules_version
            cur.text_versions_used = used
            cur.computed_at = utcnow()
            updated += 1
            if result.status == RELEVANT and was != RELEVANT:
                newly += 1
                # A bill flagged for the first time is news only if the bill itself is live.
                is_live = bill.outcome is None
                writer.emit(
                    EventSpec(
                        dedupe_key=f"{bill.uid}:flagged",
                        kind="flagged_relevant",
                        importance=HIGH if is_live else LOW,
                        bill_uid=bill.uid,
                        title=f"{bill.name} was identified as possibly affecting LGBTQ+ people.",
                        detail="Found by automatic text matching. See “Why this bill is listed” on the bill page.",
                        event_date=None,
                        source_url=bill.url,
                        source_label="Bill overview (ndlegis.gov)",
                    ),
                    backfill=not is_live or None,
                )
        db.commit()
        report.events_created += writer.written
        if updated:
            report.notes.append(f"Relevance: {updated} bills (re)checked, {newly} newly flagged")


def _collect_testimony(factory, fetcher: Fetcher, settings: Settings, report: CycleReport) -> None:
    budget = settings.max_testimony_pages_per_run
    if budget <= 0:
        return
    now = utcnow()
    with factory() as db:
        uids = _relevant_uids(db)
        if not uids:
            return
        checks = {c.bill_uid: c for c in db.scalars(select(TestimonyCheck))}
        recent_hearing = set(
            db.scalars(
                select(Hearing.bill_uid).where(
                    Hearing.starts_at.is_not(None),
                    Hearing.starts_at > now - timedelta(days=21),
                    Hearing.starts_at < now + timedelta(days=14),
                )
            )
        )
        todo = []
        for uid in uids:
            c = checks.get(uid)
            if c is None:
                todo.append((0, uid))
            elif uid in recent_hearing and (now - c.checked_at) > timedelta(hours=3):
                todo.append((1, uid))
            elif (now - c.checked_at) > timedelta(days=7):
                todo.append((2, uid))
        todo.sort()
        writer = EventWriter(db, report.run_id)
        checked = 0
        for _, uid in todo[:budget]:
            bill = db.get(Bill, uid)
            url = bill.testimony_url or testimony_page_url(bill.url)
            if not url:
                continue
            f = fetcher.get(url)
            check = checks.get(uid) or TestimonyCheck(bill_uid=uid, checked_at=now, ok=False)
            check.checked_at = utcnow()
            check.ok = f.ok
            if not f.ok:
                check.error = f.error
                db.merge(check)
                continue
            rows, warnings = parse_testimony_page(f.text, url)
            existing = {t.document_number for t in db.scalars(select(Testimony).where(Testimony.bill_uid == uid))}
            fresh = [r for r in rows if r.document_number not in existing]
            for r in fresh:
                db.add(Testimony(bill_uid=uid, first_seen_at=utcnow(), **r.__dict__))
            check.document_count = len(rows)
            check.error = "; ".join(warnings[:3]) if warnings else None
            db.merge(check)
            if fresh and uid in checks:  # first-ever read of a page is history, not news
                newest = max(fresh, key=lambda r: int(r.document_number) if r.document_number.isdigit() else 0)
                writer.emit(
                    EventSpec(
                        dedupe_key=f"{uid}:testimony:{newest.document_number}",
                        kind="testimony_published",
                        importance=LOW,
                        bill_uid=uid,
                        title=f"{len(fresh)} new testimony document{'s' if len(fresh) != 1 else ''} published for {bill.name}.",
                        source_url=url,
                        source_label="Bill testimony (ndlegis.gov)",
                    )
                )
            checked += 1
            db.commit()
        db.commit()
        report.events_created += writer.written
        if checked:
            report.notes.append(f"Testimony: {checked} bill pages checked")


def monitor_health(db: DbSession, settings: Settings, now: datetime | None = None) -> dict:
    """Used by the dashboard and the health-check workflow."""
    now = now or utcnow()
    last = last_ok_run(db)
    any_run = db.scalars(select(MonitorRun).order_by(MonitorRun.started_at.desc()).limit(1)).first()
    mode = current_mode(db, now)
    expected = interval_for(mode, settings)
    age_min = (now - last.started_at).total_seconds() / 60 if last else None
    failing_sources = db.execute(
        select(SourceCheck.source, func.max(SourceCheck.checked_at)).group_by(SourceCheck.source)
    ).all()
    latest_failures = []
    for source, when in failing_sources:
        row = db.scalars(
            select(SourceCheck).where(SourceCheck.source == source, SourceCheck.checked_at == when).limit(1)
        ).first()
        if row and not row.ok:
            latest_failures.append({"source": source, "error": row.error, "checked_at": row.checked_at})
    stale = age_min is None or age_min > max(settings.stale_after_minutes, expected * 2 + 30)
    return {
        "mode": mode,
        "expected_interval_min": expected,
        "last_ok_run": last.started_at if last else None,
        "last_ok_status": last.status if last else None,
        "last_ok_errors": (last.errors or []) if last else [],
        "last_run": any_run.started_at if any_run else None,
        "last_run_status": any_run.status if any_run else None,
        "minutes_since_ok": age_min,
        "stale": stale,
        "failing_sources": latest_failures,
    }


def bills_needing_text(db: DbSession) -> int:
    return db.scalar(
        select(func.count()).select_from(BillVersion).where(
            or_(BillVersion.text_status == "pending")
        )
    ) or 0
