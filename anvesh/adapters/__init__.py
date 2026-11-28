"""Adapters turn one source's response into Signal records."""

from anvesh.adapters.base import SourceError
from anvesh.adapters.rss import fetch_feed
from anvesh.config import Source
from anvesh.http import Http
from anvesh.signals import Signal


IMPLEMENTED = ("rss", "google_news")  # adapters fetch() can run today


def fetch(source: Source, http: Http, language: str = "en") -> list[Signal]:
    """Fetch one source and return its signals. Raises SourceError if the source is broken."""
    if source.adapter in IMPLEMENTED:
        return fetch_feed(source, http, language)
    raise SourceError(f"{source.name}: adapter '{source.adapter}' is not implemented yet")


__all__ = ["IMPLEMENTED", "SourceError", "fetch"]
