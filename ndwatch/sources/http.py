"""A polite HTTP client for official sources.

- Identifies itself with a descriptive User-Agent.
- Waits between requests (conservative rate).
- Retries temporary failures (timeouts, 429, 5xx) with backoff.
- Never raises on an HTTP error: callers get a FetchResult and decide what to do,
  so one unavailable page never stops a whole monitoring cycle.

A `ReplayFetcher` serves saved files instead of the network. Tests use it, and
so can anyone developing offline.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from ndwatch.config import Settings

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: int | None
    content: bytes
    fetched_at: datetime
    error: str | None = None
    content_type: str | None = None
    last_modified: str | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class Fetcher(Protocol):
    def get(self, url: str) -> FetchResult: ...


def now_utc() -> datetime:
    return datetime.now(UTC)


class HttpFetcher:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self._client = client or httpx.Client(
            headers={"User-Agent": settings.user_agent, "Accept-Encoding": "gzip"},
            timeout=settings.request_timeout,
            follow_redirects=True,
        )
        self._last_request = 0.0
        self.request_count = 0

    def _wait_turn(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.settings.request_interval:
            time.sleep(self.settings.request_interval - elapsed)
        self._last_request = time.monotonic()

    def get(self, url: str) -> FetchResult:
        last_error: str | None = None
        status: int | None = None
        for attempt in range(self.settings.max_retries + 1):
            self._wait_turn()
            self.request_count += 1
            try:
                resp = self._client.get(url)
                status = resp.status_code
                if resp.status_code == 200:
                    return FetchResult(
                        url=url,
                        ok=True,
                        status=200,
                        content=resp.content,
                        fetched_at=now_utc(),
                        content_type=resp.headers.get("content-type"),
                        last_modified=resp.headers.get("last-modified"),
                    )
                last_error = f"HTTP {resp.status_code}"
                if resp.status_code not in RETRYABLE_STATUS:
                    break
            except httpx.HTTPError as exc:  # timeouts, connection resets, DNS
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < self.settings.max_retries:
                time.sleep(min(2 ** (attempt + 1), 30))
        return FetchResult(
            url=url, ok=False, status=status, content=b"", fetched_at=now_utc(), error=last_error
        )

    def close(self) -> None:
        self._client.close()


def url_to_filename(url: str) -> str:
    """Stable file name for a URL, used by ReplayFetcher and the sample collector."""
    return quote(url.replace("https://", "").replace("http://", ""), safe="") or "index"


class ReplayFetcher:
    """Serves previously saved responses from a directory (no network)."""

    def __init__(self, directory: Path | str, fallback_ok: bool = False):
        self.directory = Path(directory)
        self.fallback_ok = fallback_ok
        self.requested: list[str] = []

    def get(self, url: str) -> FetchResult:
        self.requested.append(url)
        path = self.directory / url_to_filename(url)
        gz = path.with_name(path.name + ".gz")
        if path.exists() or gz.exists():
            import gzip

            content = path.read_bytes() if path.exists() else gzip.decompress(gz.read_bytes())
            return FetchResult(url=url, ok=True, status=200, content=content, fetched_at=now_utc())
        return FetchResult(
            url=url, ok=False, status=404, content=b"", fetched_at=now_utc(), error="not in replay set"
        )


class DictFetcher:
    """In-memory fetcher for unit tests: {url: bytes | int(status) | Exception-message str}."""

    def __init__(self, responses: dict[str, bytes | int]):
        self.responses = dict(responses)
        self.requested: list[str] = []

    def get(self, url: str) -> FetchResult:
        self.requested.append(url)
        value = self.responses.get(url, 404)
        if isinstance(value, bytes):
            return FetchResult(url=url, ok=True, status=200, content=value, fetched_at=now_utc())
        return FetchResult(
            url=url, ok=False, status=int(value), content=b"", fetched_at=now_utc(), error=f"HTTP {value}"
        )
