"""Pydantic models for the official ND Legislative Branch JSON API.

Field names follow the published documentation at
https://ndlegis.gov/legislative-api-documentation and were checked against live
responses (see docs/SOURCES.md). Fields the source marks as nullable stay
Optional: a missing value is stored as missing, never filled in.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


def _empty_to_none(v):
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


class ApiSession(_Base):
    id: str
    name: str
    type: str | None = None
    label: str | None = None
    folder: str | None = None
    current: bool = False
    start: date | None = None

    _clean = field_validator("type", "label", "folder", mode="before")(_empty_to_none)


class ApiAssemblySummary(_Base):
    """One entry of /api/data/assemblies.json."""

    assembly: int | None = None
    name: str | None = Field(default=None, alias="assembly_name")
    year: str | None = Field(default=None, alias="assembly_year")  # e.g. "69-2025"
    biennium_start: int | None = None
    biennium_end: int | None = None
    last_updated: datetime | None = None
    sessions: list[ApiSession] = Field(default_factory=list)


class ApiSessions(_Base):
    assembly: int
    assembly_name: str | None = None
    biennium_start: int
    biennium_end: int | None = None
    last_updated: datetime | None = None
    sessions: list[ApiSession] = Field(default_factory=list)


class ApiMember(_Base):
    id: int
    name: str
    salutation: str | None = None
    chamber: str | None = None
    party: str | None = None
    district: str | None = None
    url: str | None = None
    active: bool | None = None

    @field_validator("district", mode="before")
    @classmethod
    def _district_str(cls, v):
        return None if v is None or v == "" else str(v)

    _clean = field_validator("party", "chamber", "url", mode="before")(_empty_to_none)


class ApiMembers(_Base):
    assembly: int
    last_updated: datetime | None = None
    members: list[ApiMember] = Field(default_factory=list)


class ApiCommitteeMember(_Base):
    id: int | None = None
    name: str | None = None
    chamber: str | None = None
    is_chair: bool | None = None
    is_vice_chair: bool | None = None


class ApiCommittee(_Base):
    id: int
    name: str
    chamber: str | None = None
    type: str | None = None
    abbreviation: str | None = None
    url: str | None = None
    members: list[ApiCommitteeMember] = Field(default_factory=list)


class ApiCommittees(_Base):
    assembly: int
    last_updated: datetime | None = None
    committees: list[ApiCommittee] = Field(default_factory=list)


class ApiSponsor(_Base):
    id: int | None = None
    name: str
    type: str | None = None  # "member" or "committee"
    chamber: str | None = None
    primary: bool = False


class ApiRollCallSummary(_Base):
    id: str
    chamber: str | None = None
    date: datetime | None = None
    description: str | None = None
    division: str | None = None
    passed: bool | None = None
    total_yeas: int | None = None
    total_nays: int | None = None
    total_absent: int | None = None


class ApiAction(_Base):
    id: int
    description: str
    date: datetime | None = None
    category: str | None = None
    chamber: str | None = None
    bill_version: str | None = None
    roll_call: ApiRollCallSummary | None = None

    @field_validator("roll_call", mode="before")
    @classmethod
    def _empty_roll_call(cls, v):
        # The API sends {} when an action has no recorded vote.
        if not v:
            return None
        return v

    _clean = field_validator("category", "chamber", "bill_version", mode="before")(_empty_to_none)


class ApiVersion(_Base):
    lc_number: str
    description: str | None = None
    document_url: str | None = None


class ApiHearingCommittee(_Base):
    id: int | None = None
    name: str | None = None


class ApiHearing(_Base):
    id: int
    description: str | None = None
    type: str | None = None  # "Bill Hearing", "Committee Work", "Conference Committee"
    date: datetime | None = None
    committee: ApiHearingCommittee | None = None
    room: str | None = None

    _clean = field_validator("room", "type", mode="before")(_empty_to_none)


class ApiBill(_Base):
    name: str
    number: str
    summary: str | None = None
    title: str | None = None
    chamber: str | None = None
    session_id: str | None = None
    session_name: str | None = None
    url: str | None = None
    versions_url: str | None = None
    actions_url: str | None = None
    video_url: str | None = None
    hearing_url: str | None = None
    testimony_url: str | None = None
    current_status: str | None = None
    last_action: str | None = None
    passed: bool | None = None
    agency: str | None = None
    sponsors: list[ApiSponsor] = Field(default_factory=list)
    actions: list[ApiAction] = Field(default_factory=list)
    versions: list[ApiVersion] = Field(default_factory=list)
    hearings: list[ApiHearing] = Field(default_factory=list)

    @field_validator("number", mode="before")
    @classmethod
    def _number_str(cls, v):
        return str(v)

    _clean = field_validator(
        "summary", "title", "chamber", "current_status", "last_action", "agency", mode="before"
    )(_empty_to_none)


class ApiBills(_Base):
    assembly: int
    biennium_start: int | None = None
    last_updated: datetime | None = None
    # The live file is an object keyed by bill number. We accept a list too, in
    # case the format changes, and never rely on the key for identity.
    bills: dict[str, ApiBill] | list[ApiBill] = Field(default_factory=dict)

    def bill_list(self) -> list[ApiBill]:
        return list(self.bills.values()) if isinstance(self.bills, dict) else list(self.bills)


class ApiMemberVote(_Base):
    member_id: int | None = None
    name: str
    vote: str


class ApiRollCall(_Base):
    id: str
    session_id: str | None = None
    bill: str | None = None
    bill_version: str | None = None
    chamber: str | None = None
    date: datetime | None = None
    description: str | None = None
    division: str | None = None
    passed: bool | None = None
    total_yeas: int | None = None
    total_nays: int | None = None
    total_absent: int | None = None
    member_votes: list[ApiMemberVote] = Field(default_factory=list)


class ApiRollCalls(_Base):
    assembly: int
    last_updated: datetime | None = None
    roll_call: list[ApiRollCall] = Field(default_factory=list)


# Keys we expect in each object. If the source adds or drops keys we record a
# warning in the monitoring log instead of silently ignoring it.
EXPECTED_BILL_KEYS = {
    "name", "number", "summary", "title", "chamber", "session_id", "session_name", "url",
    "versions_url", "actions_url", "video_url", "hearing_url", "testimony_url",
    "current_status", "last_action", "passed", "agency", "sponsors", "actions", "versions",
    "hearings",
}  # fmt: skip
