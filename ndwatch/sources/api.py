"""Connector for the official ND Legislative Branch JSON API."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from ndwatch.config import BASE_URL
from ndwatch.sources.api_models import (
    EXPECTED_BILL_KEYS,
    ApiAssemblySummary,
    ApiBills,
    ApiCommittees,
    ApiMembers,
    ApiRollCalls,
    ApiSessions,
)
from ndwatch.sources.http import Fetcher, FetchResult

T = TypeVar("T", bound=BaseModel)


def assemblies_url() -> str:
    return f"{BASE_URL}/api/data/assemblies.json"


def assembly_url(assembly_year: str, dataset: str) -> str:
    """dataset is one of sessions, bills, members, committees, roll_call."""
    return f"{BASE_URL}/api/assembly/{assembly_year}/data/{dataset}.json"


@dataclass
class Parsed(Generic[T]):
    fetch: FetchResult
    data: T | None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.data is not None


def _parse(fetch: FetchResult, model: type[T]) -> Parsed[T]:
    if not fetch.ok:
        return Parsed(fetch=fetch, data=None, error=fetch.error or "fetch failed")
    try:
        raw = json.loads(fetch.content)
    except json.JSONDecodeError as exc:
        return Parsed(fetch=fetch, data=None, error=f"invalid JSON: {exc}")
    try:
        data = model.model_validate(raw)
    except ValidationError as exc:
        return Parsed(fetch=fetch, data=None, error=f"unexpected format: {exc.error_count()} errors; {str(exc)[:500]}")
    parsed = Parsed(fetch=fetch, data=data)
    if model is ApiBills:
        parsed.warnings.extend(_bill_key_drift(raw))
    return parsed


def _bill_key_drift(raw: dict) -> list[str]:
    bills = raw.get("bills") or {}
    items = bills.values() if isinstance(bills, dict) else bills
    seen: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            seen.update(item.keys())
    warnings = []
    added = seen - EXPECTED_BILL_KEYS
    missing = EXPECTED_BILL_KEYS - seen if seen else set()
    if added:
        warnings.append(f"bills.json has new fields not yet used: {sorted(added)}")
    if missing:
        warnings.append(f"bills.json is missing expected fields: {sorted(missing)}")
    return warnings


class LegislativeApi:
    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher

    def assemblies(self) -> Parsed[list[ApiAssemblySummary]]:
        fetch = self.fetcher.get(assemblies_url())
        if not fetch.ok:
            return Parsed(fetch=fetch, data=None, error=fetch.error)
        try:
            raw = json.loads(fetch.content)
            # Live format: an object keyed by assembly number ("69": {...}).
            items = raw.values() if isinstance(raw, dict) else raw
            data = [ApiAssemblySummary.model_validate(i) for i in items]
        except (json.JSONDecodeError, ValidationError, AttributeError) as exc:
            return Parsed(fetch=fetch, data=None, error=f"unexpected format: {str(exc)[:500]}")
        return Parsed(fetch=fetch, data=data)

    def sessions(self, assembly_year: str) -> Parsed[ApiSessions]:
        return _parse(self.fetcher.get(assembly_url(assembly_year, "sessions")), ApiSessions)

    def bills(self, assembly_year: str) -> Parsed[ApiBills]:
        return _parse(self.fetcher.get(assembly_url(assembly_year, "bills")), ApiBills)

    def members(self, assembly_year: str) -> Parsed[ApiMembers]:
        return _parse(self.fetcher.get(assembly_url(assembly_year, "members")), ApiMembers)

    def committees(self, assembly_year: str) -> Parsed[ApiCommittees]:
        return _parse(self.fetcher.get(assembly_url(assembly_year, "committees")), ApiCommittees)

    def roll_calls(self, assembly_year: str) -> Parsed[ApiRollCalls]:
        return _parse(self.fetcher.get(assembly_url(assembly_year, "roll_call")), ApiRollCalls)


def fix_source_url(url: str | None) -> str | None:
    """Some API URLs are missing a slash ("ndlegis.govassembly/..."). Repair only that."""
    if not url:
        return url
    return url.replace("ndlegis.govassembly/", "ndlegis.gov/assembly/")
