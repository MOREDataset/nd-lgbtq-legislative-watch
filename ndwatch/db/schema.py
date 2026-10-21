"""Database tables.

Design notes
- Every bill has a stable id `uid` = "<session_id>:<name without spaces>", e.g.
  "202501:HB1144". Session ids from the API already encode the year, so bills
  with the same number in different years or sessions never collide.
- Official facts (copied from the source), our derived fields (stage,
  relevance), and human/AI interpretations live in separate tables or columns so
  they are never mixed up.
- Nothing is deleted when it disappears from the source. Hearings that vanish
  get `removed_at`, and every meaningful change is written to `events` and
  `bill_field_history`.
- All datetimes are stored as naive UTC. Conversion to Central time happens on
  display.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Assembly(Base):
    __tablename__ = "assemblies"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # "69-2025"
    number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(80))
    biennium_start: Mapped[int | None] = mapped_column(Integer)
    biennium_end: Mapped[int | None] = mapped_column(Integer)
    source_last_updated: Mapped[datetime | None] = mapped_column(DateTime)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # "202501"
    assembly_id: Mapped[str] = mapped_column(ForeignKey("assemblies.id"))
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str | None] = mapped_column(String(40))
    label: Mapped[str | None] = mapped_column(String(80))
    folder: Mapped[str | None] = mapped_column(String(40))
    current: Mapped[bool] = mapped_column(Boolean, default=False)
    start: Mapped[date | None] = mapped_column(Date)


class Member(Base):
    __tablename__ = "members"
    uid: Mapped[str] = mapped_column(String(32), primary_key=True)  # "69-2025:3320"
    assembly_id: Mapped[str] = mapped_column(String(16), index=True)
    member_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(120))
    salutation: Mapped[str | None] = mapped_column(String(40))
    chamber: Mapped[str | None] = mapped_column(String(20))
    party: Mapped[str | None] = mapped_column(String(40))
    district: Mapped[str | None] = mapped_column(String(10))
    url: Mapped[str | None] = mapped_column(String(300))
    active: Mapped[bool | None] = mapped_column(Boolean)


class Bill(Base):
    __tablename__ = "bills"
    uid: Mapped[str] = mapped_column(String(40), primary_key=True)  # "202501:HB1144"
    assembly_id: Mapped[str] = mapped_column(String(16), index=True)
    session_id: Mapped[str] = mapped_column(String(16), index=True)
    session_name: Mapped[str | None] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(20))  # "HB 1144" (official form)
    number: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str | None] = mapped_column(String(10))  # HB, SB, HCR, SR...
    chamber: Mapped[str | None] = mapped_column(String(20))
    title: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)  # official "Relating to ..." text
    current_status: Mapped[str | None] = mapped_column(String(200))
    last_action: Mapped[str | None] = mapped_column(Text)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    agency: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(300))
    versions_url: Mapped[str | None] = mapped_column(String(300))
    actions_url: Mapped[str | None] = mapped_column(String(300))
    hearing_url: Mapped[str | None] = mapped_column(String(300))
    testimony_url: Mapped[str | None] = mapped_column(String(300))
    video_url: Mapped[str | None] = mapped_column(String(300))
    # Derived (ours, recomputed every cycle from official actions):
    stage: Mapped[str | None] = mapped_column(String(40))
    outcome: Mapped[str | None] = mapped_column(String(40))
    last_action_date: Mapped[datetime | None] = mapped_column(DateTime)
    # Bookkeeping:
    content_hash: Mapped[str | None] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)
    last_changed_at: Mapped[datetime] = mapped_column(DateTime)

    sponsors: Mapped[list[BillSponsor]] = relationship(
        back_populates="bill", cascade="all, delete-orphan", order_by="BillSponsor.position"
    )
    actions: Mapped[list[BillAction]] = relationship(
        back_populates="bill", cascade="all, delete-orphan", order_by="BillAction.position"
    )
    versions: Mapped[list[BillVersion]] = relationship(
        back_populates="bill", cascade="all, delete-orphan", order_by="BillVersion.position"
    )
    hearings: Mapped[list[Hearing]] = relationship(
        back_populates="bill", cascade="all, delete-orphan", order_by="Hearing.starts_at"
    )


class BillSponsor(Base):
    __tablename__ = "bill_sponsors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_uid: Mapped[str] = mapped_column(ForeignKey("bills.uid"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    sponsor_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[str | None] = mapped_column(String(20))
    chamber: Mapped[str | None] = mapped_column(String(20))
    primary: Mapped[bool] = mapped_column(Boolean, default=False)
    bill: Mapped[Bill] = relationship(back_populates="sponsors")


class BillAction(Base):
    __tablename__ = "bill_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_uid: Mapped[str] = mapped_column(ForeignKey("bills.uid"), index=True)
    action_id: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    date: Mapped[datetime | None] = mapped_column(DateTime)  # UTC
    date_only: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str | None] = mapped_column(String(80))
    chamber: Mapped[str | None] = mapped_column(String(20))
    bill_version: Mapped[str | None] = mapped_column(String(40))
    roll_call_id: Mapped[str | None] = mapped_column(String(40))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    bill: Mapped[Bill] = relationship(back_populates="actions")
    __table_args__ = (UniqueConstraint("bill_uid", "action_id"),)


class BillVersion(Base):
    __tablename__ = "bill_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_uid: Mapped[str] = mapped_column(ForeignKey("bills.uid"), index=True)
    lc_number: Mapped[str] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(200))
    document_url: Mapped[str | None] = mapped_column(String(300))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    # Extracted text of the official PDF (fetched once; versions do not change).
    text: Mapped[str | None] = mapped_column(Text)
    text_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|ok|failed|skipped
    text_sha256: Mapped[str | None] = mapped_column(String(64))
    text_fetched_at: Mapped[datetime | None] = mapped_column(DateTime)
    text_error: Mapped[str | None] = mapped_column(String(300))
    bill: Mapped[Bill] = relationship(back_populates="versions")
    __table_args__ = (UniqueConstraint("bill_uid", "lc_number"),)


class Hearing(Base):
    __tablename__ = "hearings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_uid: Mapped[str] = mapped_column(ForeignKey("bills.uid"), index=True)
    hearing_id: Mapped[int] = mapped_column(Integer)
    type: Mapped[str | None] = mapped_column(String(40))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)  # UTC
    committee_id: Mapped[int | None] = mapped_column(Integer)
    committee_name: Mapped[str | None] = mapped_column(String(200))
    room: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)
    bill: Mapped[Bill] = relationship(back_populates="hearings")
    __table_args__ = (UniqueConstraint("bill_uid", "hearing_id"),)


class RollCall(Base):
    __tablename__ = "roll_calls"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # "202501H00534"
    session_id: Mapped[str | None] = mapped_column(String(16), index=True)
    bill_uid: Mapped[str | None] = mapped_column(String(40), index=True)
    bill_name: Mapped[str | None] = mapped_column(String(20))
    bill_version: Mapped[str | None] = mapped_column(String(40))
    chamber: Mapped[str | None] = mapped_column(String(20))
    date: Mapped[datetime | None] = mapped_column(DateTime)
    description: Mapped[str | None] = mapped_column(String(300))
    division: Mapped[str | None] = mapped_column(String(80))
    passed: Mapped[bool | None] = mapped_column(Boolean)
    total_yeas: Mapped[int | None] = mapped_column(Integer)
    total_nays: Mapped[int | None] = mapped_column(Integer)
    total_absent: Mapped[int | None] = mapped_column(Integer)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)


class MemberVote(Base):
    __tablename__ = "member_votes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    roll_call_id: Mapped[str] = mapped_column(ForeignKey("roll_calls.id"), index=True)
    member_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    vote: Mapped[str] = mapped_column(String(20))


class Testimony(Base):
    __test__ = False  # not a pytest test class

    __tablename__ = "testimony"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_uid: Mapped[str] = mapped_column(ForeignKey("bills.uid"), index=True)
    document_number: Mapped[str] = mapped_column(String(20))
    hearing_date: Mapped[str | None] = mapped_column(String(20))  # as published, e.g. "03/24"
    hearing_time: Mapped[str | None] = mapped_column(String(20))
    committee: Mapped[str | None] = mapped_column(String(200))
    submitter: Mapped[str | None] = mapped_column(String(200))
    organization: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(200))
    city_state: Mapped[str | None] = mapped_column(String(120))
    position: Mapped[str | None] = mapped_column(String(40))  # official label, verbatim
    document_url: Mapped[str | None] = mapped_column(String(400))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("bill_uid", "document_number"),)


class TestimonyCheck(Base):
    """When we last looked at a bill's testimony page, and what we saw."""

    __tablename__ = "testimony_checks"
    bill_uid: Mapped[str] = mapped_column(String(40), primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime)
    ok: Mapped[bool] = mapped_column(Boolean)
    document_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(300))


class Relevance(Base):
    """Automatic relevance result. Recomputed when bill text or rules change."""

    __tablename__ = "relevance"
    bill_uid: Mapped[str] = mapped_column(ForeignKey("bills.uid"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), index=True)  # relevant|possible|not_relevant
    level: Mapped[str | None] = mapped_column(String(20))  # direct|indirect|uncertain
    score: Mapped[int] = mapped_column(Integer, default=0)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    rules_version: Mapped[str] = mapped_column(String(20))
    text_versions_used: Mapped[list] = mapped_column(JSON, default=list)
    computed_at: Mapped[datetime] = mapped_column(DateTime)


class ReviewDecision(Base):
    """A person's include/exclude decision. The newest one for a bill wins."""

    __tablename__ = "review_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_uid: Mapped[str] = mapped_column(ForeignKey("bills.uid"), index=True)
    decision: Mapped[str] = mapped_column(String(20))  # include|exclude
    impact: Mapped[str | None] = mapped_column(String(40))
    topics: Mapped[list | None] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Summary(Base):
    """Plain-language explanation of one specific bill version.

    kind: "human" (written by a reviewer) or "ai" (machine-generated, always
    labeled as such). The official one-line summary stays on the Bill row.
    """

    __tablename__ = "summaries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_uid: Mapped[str] = mapped_column(ForeignKey("bills.uid"), index=True)
    lc_number: Mapped[str | None] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20))
    about: Mapped[str | None] = mapped_column(Text)
    what_changes: Mapped[str | None] = mapped_column(Text)
    who_affected: Mapped[str | None] = mapped_column(Text)
    uncertain: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list | None] = mapped_column(JSON)
    author: Mapped[str | None] = mapped_column(String(80))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Event(Base):
    """One meaningful change, shown in the activity feed."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    bill_uid: Mapped[str | None] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    importance: Mapped[int] = mapped_column(Integer, default=1)  # 1 low .. 3 high
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str | None] = mapped_column(Text)
    event_date: Mapped[datetime | None] = mapped_column(DateTime, index=True)  # source date (UTC)
    event_date_only: Mapped[bool] = mapped_column(Boolean, default=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    source_url: Mapped[str | None] = mapped_column(String(400))
    source_label: Mapped[str | None] = mapped_column(String(120))
    run_id: Mapped[int | None] = mapped_column(Integer)
    # True for events created while first loading a session's history, so the
    # feed can show them without calling them "new".
    backfill: Mapped[bool] = mapped_column(Boolean, default=False)


class BillFieldHistory(Base):
    __tablename__ = "bill_field_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_uid: Mapped[str] = mapped_column(String(40), index=True)
    field: Mapped[str] = mapped_column(String(40))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime)
    run_id: Mapped[int | None] = mapped_column(Integer)


class MonitorRun(Base):
    __tablename__ = "monitor_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20))  # running|ok|partial|failed|skipped
    mode: Mapped[str | None] = mapped_column(String(20))
    trigger: Mapped[str | None] = mapped_column(String(40))
    events_created: Mapped[int] = mapped_column(Integer, default=0)
    requests_made: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[list] = mapped_column(JSON, default=list)
    errors: Mapped[list] = mapped_column(JSON, default=list)


class SourceCheck(Base):
    """One attempt to read one official source."""

    __tablename__ = "source_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    source: Mapped[str] = mapped_column(String(60), index=True)  # e.g. "bills:69-2025"
    url: Mapped[str] = mapped_column(String(400))
    checked_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    http_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    source_last_updated: Mapped[datetime | None] = mapped_column(DateTime)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    changed: Mapped[bool | None] = mapped_column(Boolean)


class SourceFact(Base):
    """A rule or notice read from an official page, e.g. the testimony deadline rule."""

    __tablename__ = "source_facts"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(400))
    checked_at: Mapped[datetime] = mapped_column(DateTime)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)


class NotificationOutbox(Base):
    """Queue for optional future channels (email). The in-app feed reads `events` directly."""

    __tablename__ = "notification_outbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime)


Index("ix_events_feed", Event.importance, Event.detected_at)
