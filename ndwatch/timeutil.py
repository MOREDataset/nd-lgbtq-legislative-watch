"""Date and time handling.

Assumption (documented in docs/SOURCES.md): the API's datetimes carry no time
zone and are local Bismarck time (America/Chicago). Action dates use the
placeholder time 23:59:59 when only the day is known; we keep those as
"date only" and never display a made-up time.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from ndwatch.config import LEGISLATURE_TZ

DATE_ONLY_TIMES = {time(23, 59, 59)}


def utcnow() -> datetime:
    """Current time as naive UTC (the storage convention)."""
    return datetime.now(UTC).replace(tzinfo=None)


def local_to_utc(dt: datetime | None) -> datetime | None:
    """Interpret a naive source datetime as Central time and return naive UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LEGISLATURE_TZ)
    return dt.astimezone(UTC).replace(tzinfo=None)


def utc_to_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC).astimezone(LEGISLATURE_TZ)


def is_date_only(dt: datetime | None) -> bool:
    return dt is not None and dt.tzinfo is None and dt.time() in DATE_ONLY_TIMES


def local_date(dt_utc: datetime | None) -> date | None:
    loc = utc_to_local(dt_utc)
    return loc.date() if loc else None


def fmt_date(dt_utc: datetime | None, date_only: bool = False, with_weekday: bool = True) -> str:
    """Human date in Central time, e.g. 'Mon, Jan 27, 2025' or 'Mon, Jan 27, 2025, 3:15 PM CT'."""
    loc = utc_to_local(dt_utc)
    if loc is None:
        return "Date not published"
    day = f"{loc:%b} {loc.day}, {loc.year}"
    if with_weekday:
        day = f"{loc:%a}, {day}"
    if date_only:
        return day
    return f"{day}, {_clock(loc)} CT"


def fmt_time(dt_utc: datetime | None) -> str:
    loc = utc_to_local(dt_utc)
    return f"{_clock(loc)} CT" if loc else ""


def _clock(loc: datetime) -> str:
    """'3:15 PM' (portable; avoids the %-I directive that Windows lacks)."""
    hour = loc.hour % 12 or 12
    return f"{hour}:{loc:%M} {loc:%p}"


def fmt_relative(dt_utc: datetime | None, now: datetime | None = None) -> str:
    if dt_utc is None:
        return "never"
    now = now or utcnow()
    secs = (now - dt_utc).total_seconds()
    if secs < 0:
        secs = -secs
        future = True
    else:
        future = False
    if secs < 90:
        s = "just now" if not future else "in a minute"
        return s
    mins = secs / 60
    if mins < 90:
        v = f"{int(mins)} minutes"
    elif mins < 60 * 36:
        v = f"{int(mins // 60)} hours"
    else:
        v = f"{int(mins // 1440)} days"
    return f"in {v}" if future else f"{v} ago"
