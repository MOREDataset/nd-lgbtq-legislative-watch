"""Read-only queries for the dashboard. Returns plain dicts so results can be cached."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ndwatch.config import Settings
from ndwatch.db.schema import (
    Bill,
    BillAction,
    BillSponsor,
    BillVersion,
    Event,
    Hearing,
    Member,
    MemberVote,
    Relevance,
    ReviewDecision,
    RollCall,
    Session,
    SourceCheck,
    SourceFact,
    Summary,
    Testimony,
    TestimonyCheck,
)
from ndwatch.monitor import monitor_health
from ndwatch.process import OUTCOME_LABELS, build_path
from ndwatch.relevance.detector import default_rules
from ndwatch.timeutil import utcnow


def latest_decisions(db: DbSession) -> dict[str, ReviewDecision]:
    out: dict[str, ReviewDecision] = {}
    for d in db.scalars(select(ReviewDecision).order_by(ReviewDecision.created_at)):
        out[d.bill_uid] = d
    return out


def tracked_uids(db: DbSession, include_possible: bool = False) -> set[str]:
    statuses = ["relevant", "possible"] if include_possible else ["relevant"]
    auto = set(db.scalars(select(Relevance.bill_uid).where(Relevance.status.in_(statuses))))
    dec = latest_decisions(db)
    inc = {u for u, d in dec.items() if d.decision == "include"}
    exc = {u for u, d in dec.items() if d.decision == "exclude"}
    return (auto | inc) - exc


def sessions(db: DbSession) -> list[dict]:
    rows = db.scalars(select(Session).order_by(Session.start.desc())).all()
    return [
        {"id": s.id, "name": s.name, "label": s.label, "type": s.type, "current": s.current,
         "start": s.start, "assembly_id": s.assembly_id}
        for s in rows
    ]


def _next_hearings(db: DbSession, uids: set[str], now: datetime) -> dict[str, Hearing]:
    rows = db.scalars(
        select(Hearing).where(Hearing.bill_uid.in_(uids), Hearing.starts_at > now, Hearing.removed_at.is_(None))
        .order_by(Hearing.starts_at)
    ).all()
    out: dict[str, Hearing] = {}
    for h in rows:
        out.setdefault(h.bill_uid, h)
    return out


def bill_cards(db: DbSession, include_possible: bool = False) -> list[dict]:
    now = utcnow()
    uids = tracked_uids(db, include_possible=include_possible)
    if not uids:
        return []
    rules = default_rules()
    rel = {r.bill_uid: r for r in db.scalars(select(Relevance).where(Relevance.bill_uid.in_(uids)))}
    dec = latest_decisions(db)
    nxt = _next_hearings(db, uids, now)
    sess = {s.id: s for s in db.scalars(select(Session))}
    primary: dict[str, str] = {}
    for sp in db.scalars(select(BillSponsor).where(BillSponsor.bill_uid.in_(uids)).order_by(BillSponsor.position)):
        if sp.primary or sp.bill_uid not in primary:
            primary.setdefault(sp.bill_uid, sp.name)
    out = []
    for b in db.scalars(select(Bill).where(Bill.uid.in_(uids))):
        r = rel.get(b.uid)
        d = dec.get(b.uid)
        s = sess.get(b.session_id)
        h = nxt.get(b.uid)
        topics = (d.topics if d and d.topics else (r.topics if r else [])) or []
        out.append({
            "uid": b.uid,
            "name": b.name,
            "kind": b.kind,
            "summary": b.summary,
            "title": b.title,
            "status": b.current_status,
            "outcome": b.outcome,
            "outcome_label": OUTCOME_LABELS.get(b.outcome) if b.outcome else None,
            "stage": b.stage,
            "session_id": b.session_id,
            "session_name": b.session_name,
            "live": bool(s and s.current) and b.outcome is None,
            "last_action": b.last_action,
            "last_action_date": b.last_action_date,
            "relevance": (r.status if r else None),
            "level": (r.level if r else None),
            "reviewed": d.decision if d else None,
            "impact": d.impact if d else None,
            "topics": topics,
            "topic_labels": [rules.topics.get(t, t) for t in topics],
            "next_hearing": {"when": h.starts_at, "type": h.type, "committee": h.committee_name, "room": h.room} if h else None,
            "primary_sponsor": primary.get(b.uid),
            "url": b.url,
        })
    out.sort(key=lambda c: (c["outcome"] is not None, -(c["last_action_date"] or datetime.min).timestamp()))
    return out


def feed(db: DbSession, uids: set[str] | None = None, limit: int = 200, min_importance: int = 1,
         since: datetime | None = None) -> list[dict]:
    q = select(Event, Bill.name, Bill.summary).join(Bill, Bill.uid == Event.bill_uid, isouter=True)
    if uids is not None:
        q = q.where(Event.bill_uid.in_(uids))
    q = q.where(Event.importance >= min_importance)
    if since:
        q = q.where(Event.detected_at >= since)
    rows = db.execute(q).all()
    items = []
    for e, name, summary in rows:
        # "Flagged by our matcher" is not legislative news for a bill that has already finished.
        if e.kind == "flagged_relevant" and e.backfill:
            continue
        items.append({
            "id": e.id, "uid": e.bill_uid, "bill": name, "bill_summary": summary, "kind": e.kind,
            "importance": e.importance, "title": e.title, "detail": e.detail, "event_date": e.event_date,
            "date_only": e.event_date_only, "detected_at": e.detected_at, "source_url": e.source_url,
            "source_label": e.source_label, "backfill": e.backfill,
        })
    items.sort(key=lambda i: (i["event_date"] or i["detected_at"]), reverse=True)
    return items[:limit]


def upcoming_hearings(db: DbSession, uids: set[str] | None, days: int = 60) -> list[dict]:
    now = utcnow()
    q = (
        select(Hearing, Bill.name, Bill.summary, Bill.hearing_url, Bill.testimony_url, Bill.url)
        .join(Bill, Bill.uid == Hearing.bill_uid)
        .where(Hearing.starts_at > now - timedelta(hours=3), Hearing.starts_at < now + timedelta(days=days),
               Hearing.removed_at.is_(None))
        .order_by(Hearing.starts_at)
    )
    if uids is not None:
        q = q.where(Hearing.bill_uid.in_(uids))
    out = []
    for h, name, summary, hurl, turl, burl in db.execute(q).all():
        out.append({
            "uid": h.bill_uid, "bill": name, "summary": summary, "when": h.starts_at, "type": h.type,
            "public": (h.type or "").lower() == "bill hearing", "committee": h.committee_name, "room": h.room,
            "hearing_url": hurl or burl, "testimony_url": turl, "first_seen_at": h.first_seen_at,
        })
    return out


def facts(db: DbSession) -> dict[str, dict]:
    return {f.key: {"value": f.value, "url": f.source_url, "checked_at": f.checked_at}
            for f in db.scalars(select(SourceFact))}


def health(db: DbSession, settings: Settings) -> dict:
    h = monitor_health(db, settings)
    latest: dict[str, SourceCheck] = {}
    for c in db.scalars(select(SourceCheck).order_by(SourceCheck.checked_at)):
        latest[c.source] = c
    ok_latest: dict[str, SourceCheck] = {}
    for c in db.scalars(select(SourceCheck).where(SourceCheck.ok.is_(True)).order_by(SourceCheck.checked_at)):
        ok_latest[c.source] = c
    h["sources"] = [
        {"source": k, "url": v.url, "checked_at": v.checked_at, "ok": v.ok, "error": v.error,
         "last_ok": ok_latest[k].checked_at if k in ok_latest else None,
         "source_last_updated": ok_latest[k].source_last_updated if k in ok_latest else None}
        for k, v in sorted(latest.items())
    ]
    return h


def bill_detail(db: DbSession, uid: str) -> dict | None:
    b = db.get(Bill, uid)
    if b is None:
        return None
    now = utcnow()
    rel = db.get(Relevance, uid)
    dec = latest_decisions(db).get(uid)
    rules = default_rules()
    members = {m.member_id: m for m in db.scalars(select(Member).where(Member.assembly_id == b.assembly_id))}
    sess = db.get(Session, b.session_id)

    sponsors = []
    for sp in b.sponsors:
        m = members.get(sp.sponsor_id) if (sp.type or "").lower() == "member" else None
        sponsors.append({
            "name": sp.name, "type": sp.type, "chamber": sp.chamber, "primary": sp.primary,
            "party": m.party if m else None, "district": m.district if m else None,
            "url": m.url if m else None, "full_name": m.name if m else None,
        })

    actions = [
        {"description": a.description, "date": a.date, "date_only": a.date_only, "chamber": a.chamber,
         "category": a.category, "roll_call_id": a.roll_call_id, "version": a.bill_version}
        for a in sorted(b.actions, key=lambda a: (a.date or datetime.min, a.position))
    ]
    path = build_path(b.name, b.chamber, list(b.actions), b.passed)

    hearings = [
        {"when": h.starts_at, "type": h.type, "public": (h.type or "").lower() == "bill hearing",
         "committee": h.committee_name, "room": h.room, "removed": h.removed_at is not None,
         "upcoming": bool(h.starts_at and h.starts_at > now), "description": h.description}
        for h in b.hearings
    ]

    votes = []
    rcs = db.scalars(select(RollCall).where(RollCall.bill_uid == uid).order_by(RollCall.date)).all()
    for rc in rcs:
        mv = db.scalars(select(MemberVote).where(MemberVote.roll_call_id == rc.id)).all()
        by = defaultdict(list)
        for v in mv:
            m = members.get(v.member_id)
            by[v.vote].append({"name": v.name, "party": m.party if m else None, "district": m.district if m else None})
        votes.append({
            "id": rc.id, "date": rc.date, "chamber": rc.chamber, "description": rc.description,
            "passed": rc.passed, "yeas": rc.total_yeas, "nays": rc.total_nays, "absent": rc.total_absent,
            "members": dict(by), "version": rc.bill_version,
        })

    versions = [
        {"lc": v.lc_number, "description": v.description, "url": v.document_url, "text_status": v.text_status}
        for v in b.versions
    ]
    testimony = [
        {"date": t.hearing_date, "time": t.hearing_time, "committee": t.committee, "name": t.submitter,
         "organization": t.organization, "position": t.position, "url": t.document_url}
        for t in db.scalars(select(Testimony).where(Testimony.bill_uid == uid))
    ]
    tcheck = db.get(TestimonyCheck, uid)
    summaries = [
        {"kind": s.kind, "lc": s.lc_number, "about": s.about, "what_changes": s.what_changes,
         "who_affected": s.who_affected, "uncertain": s.uncertain, "author": s.author,
         "needs_review": s.needs_review, "created_at": s.created_at}
        for s in db.scalars(select(Summary).where(Summary.bill_uid == uid).order_by(Summary.created_at.desc()))
    ]
    events = feed(db, {uid}, limit=500)
    return {
        "uid": b.uid, "name": b.name, "kind": b.kind, "title": b.title, "summary": b.summary,
        "status": b.current_status, "last_action": b.last_action, "passed": b.passed,
        "outcome": b.outcome, "session_name": b.session_name, "session_current": bool(sess and sess.current),
        "url": b.url, "versions_url": b.versions_url, "actions_url": b.actions_url,
        "hearing_url": b.hearing_url, "testimony_url": b.testimony_url, "video_url": b.video_url,
        "first_seen_at": b.first_seen_at, "last_changed_at": b.last_changed_at,
        "sponsors": sponsors, "actions": actions, "path": path, "hearings": hearings, "votes": votes,
        "versions": versions, "testimony": testimony,
        "testimony_checked": {"at": tcheck.checked_at, "ok": tcheck.ok, "count": tcheck.document_count} if tcheck else None,
        "summaries": summaries, "events": events,
        "relevance": {
            "status": rel.status, "level": rel.level, "score": rel.score,
            "topics": [rules.topics.get(t, t) for t in (rel.topics or [])],
            "evidence": rel.evidence or [], "computed_at": rel.computed_at,
            "texts_used": rel.text_versions_used or [],
        } if rel else None,
        "decision": {"decision": dec.decision, "impact": dec.impact, "reason": dec.reason,
                     "reviewer": dec.reviewer, "at": dec.created_at} if dec else None,
    }


def review_queue(db: DbSession) -> list[dict]:
    dec = latest_decisions(db)
    rules = default_rules()
    rows = db.execute(
        select(Bill, Relevance).join(Relevance, Relevance.bill_uid == Bill.uid)
        .where(Relevance.status.in_(["possible", "relevant"]))
        .order_by(Relevance.score.desc())
    ).all()
    out = []
    for b, r in rows:
        d = dec.get(b.uid)
        out.append({
            "uid": b.uid, "name": b.name, "summary": b.summary, "session_name": b.session_name,
            "status": r.status, "level": r.level, "score": r.score,
            "topics": [rules.topics.get(t, t) for t in r.topics or []], "evidence": r.evidence or [],
            "decision": d.decision if d else None, "impact": d.impact if d else None,
            "reason": d.reason if d else None, "url": b.url,
        })
    return out


def text_coverage(db: DbSession, uids: set[str] | None = None) -> dict:
    q = select(BillVersion.text_status)
    if uids is not None:
        q = q.where(BillVersion.bill_uid.in_(uids))
    counts: dict[str, int] = defaultdict(int)
    for (s,) in db.execute(q):
        counts[s] += 1
    return dict(counts)


def all_bill_count(db: DbSession) -> int:
    return len(db.scalars(select(Bill.uid)).all())


def action_count(db: DbSession) -> int:
    return len(db.scalars(select(BillAction.id)).all())
