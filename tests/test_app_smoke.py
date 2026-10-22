"""Every dashboard page renders without errors (SYNTHETIC data plus the real 2025 subset)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")

from ndwatch.config import Settings  # noqa: E402
from ndwatch.db.session import init_db, make_engine, session_factory  # noqa: E402
from ndwatch.monitor import run_cycle  # noqa: E402
from ndwatch.sources.http import ReplayFetcher  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def db_url(tmp_path_factory):
    path = tmp_path_factory.mktemp("app") / "app.db"
    url = f"sqlite:///{path}"
    engine = make_engine(url)
    init_db(engine)
    settings = dataclasses.replace(Settings(), request_interval=0, max_retries=0, signals_enabled=False)
    run_cycle(session_factory(engine), ReplayFetcher(ROOT / "tests/fixtures/historical"), settings,
              force=True, only_assemblies=["69-2025"])
    # Early signals: the real pages, plus one SYNTHETIC flagged item so the cards render.
    from ndwatch.db.schema import MonitorRun, Signal
    from ndwatch.monitor import CycleReport
    from ndwatch.signals import collect_signals
    from ndwatch.timeutil import utcnow

    factory = session_factory(engine)
    collect_signals(factory, ReplayFetcher(ROOT / "tests/fixtures/signals_real"),
                    dataclasses.replace(settings, signals_enabled=True), CycleReport(0, "ok", None), ["69-2025"])
    with factory() as db:
        now = utcnow()
        db.add(Signal(id="study:SYNTHETIC", kind="interim_study", body="Example Committee (SYNTHETIC)",
                      title="Study policies on gender identity <b>in</b> state agencies.", status="relevant",
                      score=10, topics=["sogi"], evidence=[{"topic": "sogi", "term": "gender identity",
                      "where": "summary", "snippet": "policies on gender identity", "weight": 10}],
                      first_seen_at=now, last_seen_at=now, extra={}, url="https://ndlegis.gov/x.pdf"))
        db.add(Signal(id="rule:SYNTHETIC", kind="agency_rule", body="Example Agency (SYNTHETIC)",
                      title="Example Agency: proposed rule changes", status="possible", score=4, topics=["schools"],
                      evidence=[], first_seen_at=now, last_seen_at=now, event_at=now,
                      extra={"notice": "https://ndlegis.gov/n.pdf"}, url="https://ndlegis.gov/events/x"))
        db.add(MonitorRun(started_at=now, status="ok"))
        db.commit()
    return url


def _render(page: str, bill: str | None = None):
    import streamlit as st

    from ndwatch.ui import views
    from ndwatch.ui.review import review

    fns = {"overview": views.overview, "bills": views.bills, "hearings": views.hearings,
           "activity": views.activity, "following": views.following, "about": views.about, "review": review,
           "signals": views.early_signals}
    st.session_state["_pages"] = {k: st.Page(v, title=k, url_path=k) for k, v in fns.items()}
    if bill:
        st.query_params["bill"] = bill
    fns[page]()


@pytest.mark.parametrize("page", ["overview", "bills", "hearings", "activity", "following", "about", "review",
                                  "signals"])
def test_page_renders(db_url, monkeypatch, page):
    monkeypatch.setenv("DATABASE_URL", db_url)
    at = st_testing.AppTest.from_function(_render, args=(page,), default_timeout=60)
    at.run()
    assert not at.exception, at.exception


@pytest.mark.parametrize("bill", ["202501:HB1144", "202501:HB1430", "202501:HB1217", "202501:NOPE1"])
def test_bill_page_renders(db_url, monkeypatch, bill):
    monkeypatch.setenv("DATABASE_URL", db_url)
    at = st_testing.AppTest.from_function(_render, args=("bills", bill), default_timeout=60)
    at.run()
    assert not at.exception, at.exception


def test_bill_page_shows_official_subject(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    at = st_testing.AppTest.from_function(_render, args=("bills", "202501:HB1144"), default_timeout=60)
    at.run()
    text = " ".join(m.value for m in at.markdown)
    assert "transgender student accommodations" in text


def test_early_signals_page_shows_items_escaped(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    at = st_testing.AppTest.from_function(_render, args=("signals",), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    html = " ".join(str(getattr(el, "proto", "")) for el in at.main)
    assert "gender identity &lt;b&gt;in&lt;/b&gt;" in html  # page text is escaped, never rendered as HTML
    assert "Example Agency" in html
