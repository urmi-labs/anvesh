"""RSS / Atom feeds, including Google News search feeds."""

import calendar
from datetime import UTC, datetime

import feedparser
import httpx

from anvesh.adapters.base import SourceError, clean_text
from anvesh.config import Source
from anvesh.http import Http
from anvesh.signals import Signal
from anvesh.state import to_iso


def _published(entry) -> str | None:
    """feedparser gives dates as UTC time tuples; turn the first one present into an ISO string."""
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            return to_iso(datetime.fromtimestamp(calendar.timegm(parsed), UTC))
    return None


def _publisher_and_title(entry, feed_title: str, google_news: bool) -> tuple[str, str]:
    title = clean_text(entry.get("title"))
    if not google_news:
        return feed_title, title
    # Google News: the real publisher is in <source>, and the title ends with " - Publisher".
    publisher = clean_text((entry.get("source") or {}).get("title")) or "Google News"
    suffix = f" - {publisher}"
    if title.endswith(suffix):
        title = title[: -len(suffix)].rstrip()
    return publisher, title


def parse_feed(source: Source, content: bytes) -> list[Signal]:
    """Turn feed bytes into signals. Entries without a title or link are skipped."""
    feed = feedparser.parse(content)
    if not feed.entries and (feed.bozo or not feed.version):
        # an HTML block page or broken XML, not an empty feed
        raise SourceError(f"{source.name}: not a valid feed")
    feed_title = clean_text(feed.feed.get("title")) or source.name
    google_news = source.adapter == "google_news"
    signals = []
    for entry in feed.entries:
        link = (entry.get("link") or "").strip()
        publisher, title = _publisher_and_title(entry, feed_title, google_news)
        if not title or not link:
            continue
        signals.append(
            Signal(
                source=source.name,
                title=title,
                link=link,
                publisher=publisher,
                published=_published(entry),
                region=source.region,
                summary="" if google_news else clean_text(entry.get("summary")),
            )
        )
    return signals


def fetch_feed(source: Source, http: Http, language: str = "en") -> list[Signal]:
    """Fetch every request of a feed source. A 304 (unchanged since last run) gives no signals."""
    signals = []
    for label, url, params in source.requests(language):
        try:
            response = http.get(url, params=params, conditional=True)
        except httpx.HTTPError as exc:
            raise SourceError(f"{label}: {type(exc).__name__}") from exc
        if response.status_code == 304:
            continue
        if response.status_code != 200:
            raise SourceError(f"{label}: HTTP {response.status_code}")
        signals.extend(parse_feed(source, response.content))
    return signals
