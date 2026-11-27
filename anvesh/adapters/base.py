"""Shared pieces for all adapters."""

import html
import re

TAG = re.compile(r"<[^>]+>")
SPACES = re.compile(r"\s+")


class SourceError(RuntimeError):
    """A source could not be read this run (bad status, not a feed, network failure)."""


def clean_text(text: str | None) -> str:
    """Strip HTML tags and entities, and collapse whitespace to single spaces."""
    if not text:
        return ""
    return SPACES.sub(" ", html.unescape(TAG.sub(" ", text))).strip()
