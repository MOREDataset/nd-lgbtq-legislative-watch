"""Runtime settings, read from environment variables (or Streamlit secrets in the app).

Nothing secret is ever hardcoded here. See `.env.example` for the full list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

# The Legislature meets in Bismarck, which is on Central time.
LEGISLATURE_TZ = ZoneInfo("America/Chicago")

BASE_URL = "https://ndlegis.gov"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        return default


@dataclass(frozen=True)
class PollingPolicy:
    """How often the monitor should do a full check, in minutes, by period."""

    active_session: int = 60
    prefiling: int = 120
    off_season: int = 720
    # A run is allowed this many minutes early so an hourly cron that fires a
    # little early is not skipped.
    slack: int = 10


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///data/ndwatch.db"
    user_agent: str = (
        "ND-LGBTQ-Legislative-Watch/0.1 (+https://github.com/MOREDataset/nd-lgbtq-legislative-watch)"
    )
    # Minimum seconds between two requests to ndlegis.gov.
    request_interval: float = 1.5
    request_timeout: float = 60.0
    max_retries: int = 3
    # How many bill-text PDFs to download per run (backfill happens over several runs).
    max_pdfs_per_run: int = 1000
    # How many testimony pages to check per run.
    max_testimony_pages_per_run: int = 60
    # How many assemblies back to ingest (1 = only the newest).
    assemblies_to_track: int = 1
    # Extra assemblies to always ingest, e.g. "69-2025" for historical validation.
    extra_assemblies: tuple[str, ...] = ()
    stale_after_minutes: int = 180
    # Early signals: interim committees, agency rule hearings, ballot measures, tracker cross-check.
    signals_enabled: bool = True
    max_signal_docs_per_run: int = 80
    polling: PollingPolicy = field(default_factory=PollingPolicy)
    admin_password: str | None = None


def load_settings() -> Settings:
    extra = tuple(
        a.strip() for a in (_env("NDWATCH_EXTRA_ASSEMBLIES", "") or "").split(",") if a.strip()
    )
    return Settings(
        database_url=_normalize_db_url(_env("DATABASE_URL", Settings.database_url)),
        user_agent=_env("NDWATCH_USER_AGENT", Settings.user_agent),
        request_interval=_env_float("NDWATCH_REQUEST_INTERVAL", Settings.request_interval),
        request_timeout=_env_float("NDWATCH_REQUEST_TIMEOUT", Settings.request_timeout),
        max_retries=_env_int("NDWATCH_MAX_RETRIES", Settings.max_retries),
        max_pdfs_per_run=_env_int("NDWATCH_MAX_PDFS_PER_RUN", Settings.max_pdfs_per_run),
        max_testimony_pages_per_run=_env_int(
            "NDWATCH_MAX_TESTIMONY_PAGES_PER_RUN", Settings.max_testimony_pages_per_run
        ),
        assemblies_to_track=_env_int("NDWATCH_ASSEMBLIES_TO_TRACK", Settings.assemblies_to_track),
        extra_assemblies=extra,
        stale_after_minutes=_env_int("NDWATCH_STALE_AFTER_MINUTES", Settings.stale_after_minutes),
        signals_enabled=(_env("NDWATCH_SIGNALS", "on") or "on").lower() not in ("0", "off", "false", "no"),
        max_signal_docs_per_run=_env_int("NDWATCH_MAX_SIGNAL_DOCS_PER_RUN", Settings.max_signal_docs_per_run),
        polling=PollingPolicy(
            active_session=_env_int("NDWATCH_POLL_ACTIVE_MIN", PollingPolicy.active_session),
            prefiling=_env_int("NDWATCH_POLL_PREFILING_MIN", PollingPolicy.prefiling),
            off_season=_env_int("NDWATCH_POLL_OFFSEASON_MIN", PollingPolicy.off_season),
        ),
        admin_password=_env("NDWATCH_ADMIN_PASSWORD"),
    )


def _normalize_db_url(url: str) -> str:
    """Hosted providers hand out `postgres://` URLs; SQLAlchemy wants an explicit driver."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url
