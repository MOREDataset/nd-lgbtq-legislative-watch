"""Streamlit plumbing: settings from secrets/env, one DB engine, short-lived caches."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import streamlit as st

from ndwatch.config import Settings, load_settings
from ndwatch.db.session import init_db, make_engine, session_factory

CACHE_SECONDS = 120


def _export_secrets() -> None:
    """Streamlit Cloud provides secrets via st.secrets; copy known ones into the environment."""
    try:
        for key in ("DATABASE_URL", "NDWATCH_ADMIN_PASSWORD"):
            if key in st.secrets and not os.environ.get(key):
                os.environ[key] = str(st.secrets[key])
    except Exception:  # no secrets file locally is fine
        pass


@st.cache_resource(show_spinner=False)
def settings() -> Settings:
    _export_secrets()
    return load_settings()


@st.cache_resource(show_spinner=False)
def _factory():
    engine = make_engine(settings().database_url)
    init_db(engine)
    return session_factory(engine)


def db_session():
    return _factory()()


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def _run(key: str, _fn: Callable) -> Any:
    with db_session() as db:
        return _fn(db)


def cached(key: str, fn: Callable) -> Any:
    """Run a read query with a short cache. `key` must uniquely describe the query."""
    return _run(key, fn)


def clear_cache() -> None:
    _run.clear()
