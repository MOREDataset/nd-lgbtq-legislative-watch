"""Store official records and detect meaningful changes.

Everything here is idempotent: running the same input twice produces no new
rows and no new events. Each event has a `dedupe_key`; an event whose key
already exists is never written again.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import insert, select
from sqlalchemy.orm import Session as DbSession

from ndwatch.db.schema import (
    Assembly,
    Bill,
    BillAction,
    BillFieldHistory,
    BillSponsor,
    BillVersion,
    Event,
    Hearing,
    Member,
    MemberVote,
    RollCall,
    Session,
    Summary,
)
from ndwatch.events import HIGH, LOW, MEDIUM, describe_action
from ndwatch.process import bill_kind, build_path, outcome_label
from ndwatch.sources.api import fix_source_url
from ndwatch.sources.api_models import (
    ApiAssemblySummary,
    ApiBill,
    ApiMember,
    ApiRollCall,
    ApiSession,
)
from ndwatch.timeutil import fmt_date, is_date_only, local_to_utc, utcnow


def bill_uid(session_id: str, name: str) -> str:
    return f"{session_id}:{name.replace(' ', '').upper()}"


@dataclass
class EventSpec:
    dedupe_key: str
    kind: str
    importance: int
    title: str
    bill_uid: str | None = None
    detail: str | None = None
    event_date: datetime | None = None
    event_date_only: bool = False
    source_url: str | None = None
    source_label: str | None = None


@dataclass
class IngestStats:
    bills_new: int = 0
    bills_changed: int = 0
    events: list[EventSpec] = field(default_factory=list)
    changed_bill_uids: set[str] = field(default_factory=set)


class EventWriter:
    """Writes events once. Keeps an in-memory set so one run never duplicates."""

    def __init__(self, db: DbSession, run_id: int | None, backfill: bool = False):
        self.db = db
        self.run_id = run_id
        self.backfill = backfill
        self._seen: set[str] = set()
        self._preloaded = False
        self.roll_call_ids: set[str] | None = None
        self.written = 0

    def preload(self) -> None:
        """Load existing event keys and roll call ids at once (one query instead of one per row)."""
        self._seen.update(self.db.scalars(select(Event.dedupe_key)))
        self.roll_call_ids = set(self.db.scalars(select(RollCall.id)))
        self._preloaded = True

    def has_roll_call(self, rc_id: str) -> bool:
        if self.roll_call_ids is None:
            self.roll_call_ids = set(self.db.scalars(select(RollCall.id)))
        return rc_id in self.roll_call_ids

    def exists(self, key: str) -> bool:
        if key in self._seen:
            return True
        if self._preloaded:
            return False
        hit = self.db.execute(select(Event.id).where(Event.dedupe_key == key)).first()
        if hit:
            self._seen.add(key)
            return True
        return False

    def emit(self, spec: EventSpec, backfill: bool | None = None) -> bool:
        if self.exists(spec.dedupe_key):
            return False
        self._seen.add(spec.dedupe_key)
        self.db.add(
            Event(
                dedupe_key=spec.dedupe_key[:200],
                bill_uid=spec.bill_uid,
                kind=spec.kind,
                importance=spec.importance,
                title=spec.title[:300],
                detail=spec.detail,
                event_date=spec.event_date,
                event_date_only=spec.event_date_only,
                detected_at=utcnow(),
                source_url=spec.source_url,
                source_label=spec.source_label,
                run_id=self.run_id,
                backfill=self.backfill if backfill is None else backfill,
            )
        )
        self.written += 1
        return True


# ---------------------------------------------------------------- assemblies


def upsert_assembly(db: DbSession, a: ApiAssemblySummary) -> Assembly | None:
    if not a.year:
        return None
    row = db.get(Assembly, a.year) or Assembly(id=a.year, number=a.assembly or 0)
    row.number = a.assembly or row.number
    row.name = a.name
    row.biennium_start = a.biennium_start
    row.biennium_end = a.biennium_end
    row.source_last_updated = local_to_utc(a.last_updated)
    db.add(row)
    for s in a.sessions:
        upsert_session(db, a.year, s)
    return row


def upsert_session(db: DbSession, assembly_id: str, s: ApiSession) -> Session:
    row = db.get(Session, s.id) or Session(id=s.id, assembly_id=assembly_id, name=s.name)
    row.assembly_id = assembly_id
    row.name = s.name
    row.type = s.type
    row.label = s.label
    row.folder = s.folder
    row.current = s.current
    row.start = s.start
    db.add(row)
    return row


def upsert_members(db: DbSession, assembly_id: str, members: list[ApiMember]) -> int:
    n = 0
    for m in members:
        uid = f"{assembly_id}:{m.id}"
        row = db.get(Member, uid) or Member(uid=uid, assembly_id=assembly_id, member_id=m.id, name=m.name)
        row.name, row.salutation, row.chamber = m.name, m.salutation, m.chamber
        row.party, row.district, row.url, row.active = m.party, m.district, m.url, m.active
        db.add(row)
        n += 1
    return n


# ---------------------------------------------------------------- bills


def _hash_bill(b: ApiBill) -> str:
    return hashlib.sha256(json.dumps(b.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


TRACKED_FIELDS = ("title", "summary", "current_status", "last_action", "passed", "chamber")


def upsert_bill(
    db: DbSession,
    assembly_id: str,
    api: ApiBill,
    writer: EventWriter,
    run_id: int | None,
    session_name_fallback: str | None = None,
) -> tuple[Bill, bool, bool]:
    """Insert or update one bill. Returns (bill, is_new, changed)."""
    now = utcnow()
    session_id = api.session_id or "unknown"
    uid = bill_uid(session_id, api.name)
    digest = _hash_bill(api)
    bill = db.get(Bill, uid)
    is_new = bill is None
    if not is_new and bill.content_hash == digest:
        bill.last_seen_at = now
        return bill, False, False

    if is_new:
        bill = Bill(
            uid=uid,
            assembly_id=assembly_id,
            session_id=session_id,
            name=api.name,
            number=api.number,
            first_seen_at=now,
            last_seen_at=now,
            last_changed_at=now,
        )
        db.add(bill)
    else:
        for f in TRACKED_FIELDS:
            old, new = getattr(bill, f), getattr(api, f)
            if old != new:
                db.add(
                    BillFieldHistory(
                        bill_uid=uid, field=f, old_value=None if old is None else str(old),
                        new_value=None if new is None else str(new), changed_at=now, run_id=run_id,
                    )
                )

    bill.session_name = api.session_name or session_name_fallback
    bill.kind = bill_kind(api.name)
    bill.chamber = api.chamber
    bill.title = api.title
    bill.summary = api.summary
    bill.current_status = api.current_status
    bill.last_action = api.last_action
    bill.passed = api.passed
    bill.agency = api.agency
    bill.url = fix_source_url(api.url)
    bill.versions_url = fix_source_url(api.versions_url)
    bill.actions_url = fix_source_url(api.actions_url)
    bill.hearing_url = fix_source_url(api.hearing_url)
    bill.testimony_url = fix_source_url(api.testimony_url)
    bill.video_url = fix_source_url(api.video_url)
    bill.content_hash = digest
    bill.last_seen_at = now
    bill.last_changed_at = now

    if is_new:
        writer.emit(
            EventSpec(
                dedupe_key=f"{uid}:new",
                kind="new_bill",
                importance=MEDIUM,
                bill_uid=uid,
                title=f"New bill: {api.name}" + (f" — {api.summary}" if api.summary else ""),
                detail=api.title,
                event_date=_first_action_date(api),
                event_date_only=True,
                source_url=bill.url,
                source_label="Bill overview (ndlegis.gov)",
            )
        )

    _sync_sponsors(db, bill, api)
    _sync_actions(db, bill, api, writer, now)
    _sync_versions(db, bill, api, writer, now)
    _sync_hearings(db, bill, api, writer, now)
    _update_path(db, bill, writer)
    return bill, is_new, True


def _first_action_date(api: ApiBill) -> datetime | None:
    dates = [a.date for a in api.actions if a.date]
    return local_to_utc(min(dates)) if dates else None


def _sync_sponsors(db: DbSession, bill: Bill, api: ApiBill) -> None:
    new = [(s.id, s.name, s.type, s.chamber, s.primary) for s in api.sponsors]
    old = [(s.sponsor_id, s.name, s.type, s.chamber, s.primary) for s in bill.sponsors]
    if new == old:
        return
    if old:
        db.add(
            BillFieldHistory(
                bill_uid=bill.uid, field="sponsors", old_value=json.dumps([o[1] for o in old]),
                new_value=json.dumps([n[1] for n in new]), changed_at=utcnow(),
            )
        )
    if old:
        bill.sponsors.clear()
        db.flush()
    for i, s in enumerate(api.sponsors):
        bill.sponsors.append(
            BillSponsor(position=i, sponsor_id=s.id, name=s.name, type=s.type, chamber=s.chamber, primary=s.primary)
        )


def _sync_actions(db: DbSession, bill: Bill, api: ApiBill, writer: EventWriter, now: datetime) -> None:
    existing = {a.action_id: a for a in bill.actions}
    for pos, a in enumerate(api.actions):
        row = existing.get(a.id)
        date_only = is_date_only(a.date)
        when = local_to_utc(a.date)
        rc = a.roll_call
        if row is None:
            row = BillAction(action_id=a.id, first_seen_at=now, description=a.description, position=pos)
            bill.actions.append(row)
            ev = describe_action(
                bill.name, a.description, a.chamber,
                rc.total_yeas if rc else None, rc.total_nays if rc else None,
            )
            detail = f"Official record: “{a.description}”"
            if rc and rc.total_absent is not None:
                detail += f" — Recorded vote: {rc.total_yeas} yes, {rc.total_nays} no, {rc.total_absent} absent or excused."
            # While loading history for the first time, routine steps stay out of the feed.
            if ev.importance >= MEDIUM or not writer.backfill:
                writer.emit(
                    EventSpec(
                        dedupe_key=f"{bill.uid}:action:{a.id}",
                        kind=ev.kind,
                        importance=ev.importance,
                        bill_uid=bill.uid,
                        title=ev.title,
                        detail=detail,
                        event_date=when,
                        event_date_only=date_only,
                        source_url=bill.actions_url or bill.url,
                        source_label="Bill actions (ndlegis.gov)",
                    )
                )
        row.position = pos
        row.description = a.description
        row.date = when
        row.date_only = date_only
        row.category = a.category
        row.chamber = a.chamber
        row.bill_version = a.bill_version
        row.roll_call_id = rc.id if rc else None
        # Make sure a roll call summary exists even before roll_call.json is read.
        if rc and not writer.has_roll_call(rc.id):
            writer.roll_call_ids.add(rc.id)
            db.add(
                RollCall(
                    id=rc.id, session_id=bill.session_id, bill_uid=bill.uid, bill_name=bill.name,
                    bill_version=a.bill_version, chamber=rc.chamber, date=local_to_utc(rc.date),
                    description=rc.description, division=rc.division, passed=rc.passed,
                    total_yeas=rc.total_yeas, total_nays=rc.total_nays, total_absent=rc.total_absent,
                    first_seen_at=now,
                )
            )
    bill.last_action_date = max((r.date for r in bill.actions if r.date), default=None)


def _sync_versions(db: DbSession, bill: Bill, api: ApiBill, writer: EventWriter, now: datetime) -> None:
    existing = {v.lc_number: v for v in bill.versions}
    # Versions have no date of their own; use the first official action that names the version.
    version_dates: dict[str, datetime] = {}
    for a in api.actions:
        if a.bill_version and a.date and a.bill_version not in version_dates:
            version_dates[a.bill_version] = a.date
    for pos, v in enumerate(api.versions):
        row = existing.get(v.lc_number)
        if row is None:
            row = BillVersion(lc_number=v.lc_number, first_seen_at=now, position=pos, text_status="pending")
            bill.versions.append(row)
            if pos > 0:  # the first version is the bill itself, covered by "new bill"
                desc = (v.description or "new version").strip()
                writer.emit(
                    EventSpec(
                        dedupe_key=f"{bill.uid}:version:{v.lc_number}",
                        kind="new_version",
                        importance=MEDIUM,
                        bill_uid=bill.uid,
                        title=f"A new version of {bill.name} was published ({_version_label(desc)}).",
                        detail=f"Official version description: “{desc}” (LC {v.lc_number}).",
                        event_date=local_to_utc(version_dates.get(v.lc_number)),
                        event_date_only=True,
                        source_url=v.document_url or bill.versions_url,
                        source_label="Bill text (ndlegis.gov)",
                    )
                )
                # Summaries written for older versions now need another look.
                for s in [] if writer.backfill else db.scalars(select(Summary).where(Summary.bill_uid == bill.uid)):
                    if s.lc_number != v.lc_number:
                        s.needs_review = True
        row.position = pos
        row.description = v.description
        row.document_url = v.document_url


def _version_label(desc: str) -> str:
    d = desc.lower()
    if d.startswith("prepared by"):
        return "a proposed amendment, not necessarily adopted"
    if d.startswith("adopted by"):
        return "an amendment adopted by a committee"
    if "engross" in d:
        return "updated text including adopted amendments"
    if "amend" in d:
        return "proposed or adopted amendment"
    if "enroll" in d:
        return "final text as passed by both chambers"
    if "introduc" in d:
        return "as introduced"
    return desc


def _hearing_key(h) -> tuple:
    return (h.starts_at, (h.room or "").strip().lower())


def _sync_hearings(db: DbSession, bill: Bill, api: ApiBill, writer: EventWriter, now: datetime) -> None:
    existing = {h.hearing_id: h for h in bill.hearings}
    seen: set[int] = set()
    for h in api.hearings:
        seen.add(h.id)
        starts = local_to_utc(h.date)
        row = existing.get(h.id)
        committee = h.committee.name if h.committee else None
        htype = h.type or "Hearing"
        public = htype.lower() == "bill hearing"
        what = "a public committee hearing" if public else f"a {htype.lower()} session"
        if row is None:
            row = Hearing(
                hearing_id=h.id, first_seen_at=now, last_seen_at=now, starts_at=starts,
                type=h.type, committee_id=h.committee.id if h.committee else None,
                committee_name=committee, room=h.room, description=h.description,
            )
            bill.hearings.append(row)
            upcoming = starts is not None and starts > now
            verb = "is scheduled for" if (upcoming or starts is None) else "had"
            writer.emit(
                EventSpec(
                    dedupe_key=f"{bill.uid}:hearing:{h.id}:new",
                    kind="hearing_scheduled" if public else "work_session_scheduled",
                    importance=HIGH if (public and upcoming) else (MEDIUM if public else LOW),
                    bill_uid=bill.uid,
                    title=f"{bill.name} {verb} {what}: {fmt_date(starts)}"
                    + (f", {committee}" if committee else "")
                    + (f", room {h.room}" if h.room else "")
                    + ".",
                    detail=None if public else "Committee work sessions are not public hearings; testimony is not taken online for them.",
                    event_date=starts,
                    source_url=bill.hearing_url or bill.url,
                    source_label="Bill hearings (ndlegis.gov)",
                ),
                backfill=writer.backfill or (starts is not None and starts < now) or None,
            )
        else:
            if (row.starts_at, (row.room or "")) != (starts, h.room or "") and row.removed_at is None:
                before = fmt_date(row.starts_at) + (f", room {row.room}" if row.room else "")
                after = fmt_date(starts) + (f", room {h.room}" if h.room else "")
                writer.emit(
                    EventSpec(
                        dedupe_key=f"{bill.uid}:hearing:{h.id}:moved:{starts}:{h.room}",
                        kind="hearing_changed",
                        importance=HIGH,
                        bill_uid=bill.uid,
                        title=f"The {htype.lower()} for {bill.name} changed: now {after}.",
                        detail=f"Previously listed as {before}.",
                        event_date=starts,
                        source_url=bill.hearing_url or bill.url,
                        source_label="Bill hearings (ndlegis.gov)",
                    )
                )
            row.starts_at = starts
            row.room = h.room
            row.type = h.type
            row.committee_id = h.committee.id if h.committee else None
            row.committee_name = committee
            row.description = h.description
            row.last_seen_at = now
            row.removed_at = None
    for hid, row in existing.items():
        if hid not in seen and row.removed_at is None:
            row.removed_at = now
            if row.starts_at and row.starts_at > now:
                writer.emit(
                    EventSpec(
                        dedupe_key=f"{bill.uid}:hearing:{hid}:removed:{row.starts_at}",
                        kind="hearing_removed",
                        importance=HIGH,
                        bill_uid=bill.uid,
                        title=f"The {(row.type or 'hearing').lower()} for {bill.name} previously listed for {fmt_date(row.starts_at)} is no longer on the official list.",
                        detail="This can mean it was cancelled or rescheduled. Check the official hearing page.",
                        event_date=row.starts_at,
                        source_url=bill.hearing_url or bill.url,
                        source_label="Bill hearings (ndlegis.gov)",
                    )
                )


def _update_path(db: DbSession, bill: Bill, writer: EventWriter) -> None:
    path = build_path(bill.name, bill.chamber, bill.actions, bill.passed, title=bill.title)
    old_outcome = bill.outcome
    bill.stage = path.current_key or ("final" if path.outcome else None)
    bill.outcome = path.outcome
    if path.outcome and path.outcome != old_outcome:
        writer.emit(
            EventSpec(
                dedupe_key=f"{bill.uid}:outcome:{path.outcome}",
                kind=f"outcome_{path.outcome}",
                importance=HIGH,
                bill_uid=bill.uid,
                title=f"Final outcome for {bill.name}: {outcome_label(path.outcome, bill.name, bill.title).lower()}.",
                detail=f"Official status: “{bill.current_status}”" if bill.current_status else None,
                event_date=bill.last_action_date,
                event_date_only=True,
                source_url=bill.actions_url or bill.url,
                source_label="Bill actions (ndlegis.gov)",
            )
        )


# ---------------------------------------------------------------- roll calls


def upsert_roll_calls(db: DbSession, roll_calls: list[ApiRollCall]) -> int:
    """Store full roll calls with individual votes. Returns how many were new or completed."""
    now = utcnow()
    n = 0
    complete = set(db.scalars(select(MemberVote.roll_call_id).distinct()))
    existing = {r.id: r for r in db.scalars(select(RollCall))}
    votes: list[dict] = []
    for rc in roll_calls:
        if rc.id in complete:
            continue
        row = existing.get(rc.id)
        uid = bill_uid(rc.session_id, rc.bill) if (rc.session_id and rc.bill) else None
        if row is None:
            row = RollCall(id=rc.id, first_seen_at=now)
            db.add(row)
        row.session_id = rc.session_id
        row.bill_uid = uid
        row.bill_name = rc.bill
        row.bill_version = rc.bill_version
        row.chamber = rc.chamber
        row.date = local_to_utc(rc.date)
        row.description = rc.description
        row.division = rc.division
        row.passed = rc.passed
        row.total_yeas, row.total_nays, row.total_absent = rc.total_yeas, rc.total_nays, rc.total_absent
        votes.extend(
            {"roll_call_id": rc.id, "member_id": mv.member_id, "name": mv.name, "vote": mv.vote}
            for mv in rc.member_votes
        )
        n += 1
    db.flush()  # roll calls first, then all individual votes in one bulk insert
    for i in range(0, len(votes), 5000):
        db.execute(insert(MemberVote), votes[i : i + 5000])
    return n


def importance_label(level: int) -> str:
    return {HIGH: "Important", MEDIUM: "Update", LOW: "Routine"}.get(level, "Update")
