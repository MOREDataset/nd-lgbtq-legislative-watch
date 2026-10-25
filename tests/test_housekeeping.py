"""Calendar-based polling floor, efficient latest-check lookup, and history pruning (synthetic data)."""

from datetime import date, datetime, timedelta

from ndwatch.db.schema import MonitorRun, SourceCheck
from ndwatch.monitor import (
    MODE_ACTIVE,
    MODE_OFF,
    MODE_PREFILING,
    calendar_mode,
    current_mode,
    latest_checks,
    prune_history,
)


def test_calendar_mode_follows_nd_biennial_calendar():
    assert calendar_mode(date(2097, 1, 10)) == MODE_ACTIVE  # odd year, session months
    assert calendar_mode(date(2097, 4, 30)) == MODE_ACTIVE
    assert calendar_mode(date(2097, 5, 10)) == MODE_PREFILING  # session wrap-up
    assert calendar_mode(date(2097, 8, 1)) is None
    assert calendar_mode(date(2098, 3, 1)) is None  # even year: interim
    assert calendar_mode(date(2098, 11, 20)) == MODE_PREFILING  # prefiling / organizational session
    assert calendar_mode(date(2098, 12, 5)) == MODE_PREFILING


def test_calendar_is_a_floor_under_empty_data(factory):
    with factory() as db:
        assert current_mode(db, datetime(2098, 12, 5, 12)) == MODE_PREFILING
        assert current_mode(db, datetime(2098, 7, 1, 12)) == MODE_OFF
        assert current_mode(db, datetime(2099, 2, 1, 12)) == MODE_ACTIVE


def _check(source, at, ok=True):
    return SourceCheck(source=source, url="https://example.invalid", checked_at=at, ok=ok)


def test_latest_checks_and_pruning(factory):
    now = datetime(2098, 6, 1, 12)
    with factory() as db:
        for days in (200, 100, 90, 1):
            db.add(_check("bills:x", now - timedelta(days=days)))
        db.add(_check("bills:x", now - timedelta(hours=1), ok=False))
        db.add(_check("rare", now - timedelta(days=300)))  # only ever checked long ago
        db.add(MonitorRun(started_at=now - timedelta(days=30), status="skipped"))
        db.add(MonitorRun(started_at=now - timedelta(days=30), status="ok"))
        db.add(MonitorRun(started_at=now - timedelta(days=1), status="skipped"))
        db.commit()

        latest = latest_checks(db)
        assert latest["bills:x"].ok is False
        assert latest_checks(db, ok_only=True)["bills:x"].checked_at == now - timedelta(days=1)

        checks, runs = prune_history(db, now)
        db.commit()
        assert (checks, runs) == (3, 1)
        left = sorted((c.source, c.checked_at) for c in db.query(SourceCheck))
        assert ("rare", now - timedelta(days=300)) in left  # latest of its source is kept
        assert len(left) == 3
        assert db.query(MonitorRun).count() == 2
