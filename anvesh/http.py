"""One HTTP client for every source: polite rate limits, retries, timeouts and ETag caching."""

import os
import time
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from anvesh import __version__
from anvesh.state import Table, utc_now

TIMEOUT_SECONDS = 15
RETRIES = 2  # extra attempts after the first one
BACKOFF_SECONDS = (2, 5)  # wait before retry 1 and retry 2
MAX_RETRY_AFTER = 30  # never wait longer than this for a server's Retry-After
MIN_INTERVAL_PER_HOST = 1.0  # at most one request a second to the same host
RETRY_STATUSES = {429, 500, 502, 503, 504}


def build_user_agent(contact: str | None = None) -> str:
    """Name the project and, if given, a contact address. SEC EDGAR requires the contact."""
    contact = contact if contact is not None else os.environ.get("RADAR_CONTACT", "")
    agent = f"anvesh/{__version__} (+https://github.com/urmi-labs/anvesh"
    if contact:
        agent += f"; {contact}"
    return agent + ")"


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - utc_now()).total_seconds()
        except (TypeError, ValueError):
            return None
    return max(0.0, min(seconds, MAX_RETRY_AFTER))


class Http:
    def __init__(
        self,
        cache: Table | None = None,
        client: httpx.Client | None = None,
        user_agent: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.cache = cache  # state table holding ETag / Last-Modified per URL
        self.client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True)
        self.client.headers["User-Agent"] = user_agent or build_user_agent()
        self.sleep = sleep
        self.clock = clock
        self._last_request: dict[str, float] = {}

    def _wait_for_host(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last_request.get(host)
        if last is not None:
            wait = MIN_INTERVAL_PER_HOST - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self._last_request[host] = self.clock()

    def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        conditional: bool = False,
    ) -> httpx.Response:
        """GET a URL. With conditional=True, a 304 response means "unchanged since last run".

        Retries timeouts, connection errors, 429 and 5xx. Raises httpx.HTTPError only if
        every attempt failed to get any response at all.
        """
        headers = dict(headers or {})
        cache_key = str(httpx.URL(url, params=params))
        if conditional and self.cache is not None and (saved := self.cache.get(cache_key)):
            if saved.get("etag"):
                headers["If-None-Match"] = saved["etag"]
            if saved.get("last_modified"):
                headers["If-Modified-Since"] = saved["last_modified"]

        for attempt in range(RETRIES + 1):
            self._wait_for_host(url)
            try:
                response = self.client.get(url, params=params, headers=headers)
            except httpx.TransportError:
                if attempt == RETRIES:
                    raise
                self.sleep(BACKOFF_SECONDS[attempt])
                continue
            if response.status_code in RETRY_STATUSES and attempt < RETRIES:
                retry_after = _retry_after_seconds(response)
                self.sleep(retry_after if retry_after is not None else BACKOFF_SECONDS[attempt])
                continue
            break

        if conditional and self.cache is not None and response.status_code == 200:
            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")
            if etag or last_modified:
                self.cache.upsert(cache_key, {"etag": etag, "last_modified": last_modified})
        return response
