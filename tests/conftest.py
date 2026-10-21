from __future__ import annotations

import dataclasses

import pytest

from ndwatch.config import Settings
from ndwatch.db.session import init_db, make_engine, session_factory


@pytest.fixture
def factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    return session_factory(engine)


@pytest.fixture
def settings():
    return dataclasses.replace(Settings(), request_interval=0, max_retries=0, assemblies_to_track=1)
