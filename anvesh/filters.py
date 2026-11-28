"""Pre-filter: keep only recent signals that look like a startup raising money.

This runs before anything expensive (dedupe, classification, job lookups), so it is
cheap regex and date math only. Every decision has a reason, so a run can report
how many signals were dropped and why.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from anvesh.config import FiltersConfig, FundingFilter, Source, WindowSettings
from anvesh.signals import Signal
from anvesh.state import from_iso

# Reasons a signal is dropped (also the keys of FilterResult.dropped)
TOO_OLD = "too_old"
UNDATED = "undated"
NOT_FUNDING = "not_funding"
EXCLUDED = "excluded"


def in_window(signal: Signal, now: datetime, window: WindowSettings, lag_hours: int = 0) -> str | None:
    """None if the signal is recent enough, otherwise the reason it is dropped."""
    if signal.published is None:
        # keep: no date, so it counts as published now (first time seen); dedupe stops repeats
        return None if window.undated == "keep" else UNDATED
    age = now - from_iso(signal.published)
    if age > timedelta(hours=window.hours + lag_hours):
        return TOO_OLD
    return None  # a date slightly in the future (clock skew) is also kept


class FundingMatcher:
    """Compiles the include/exclude patterns once, then checks many signals."""

    def __init__(self, funding: FundingFilter):
        self.fields = funding.match_fields
        self.include = [re.compile(p, re.IGNORECASE) for p in funding.include]
        self.exclude = [re.compile(p, re.IGNORECASE) for p in funding.exclude]

    def check(self, signal: Signal) -> str | None:
        """None if it looks like a funding story, otherwise the reason it is dropped."""
        text = " ".join(getattr(signal, f) for f in self.fields)
        if any(p.search(text) for p in self.exclude):
            return EXCLUDED  # exclude wins: "X raises funds before IPO" is still an IPO story
        if not any(p.search(text) for p in self.include):
            return NOT_FUNDING
        return None


@dataclass
class FilterResult:
    kept: list[Signal] = field(default_factory=list)
    dropped: Counter = field(default_factory=Counter)  # reason -> count


def apply_filters(
    signals: list[Signal], sources: list[Source], config: FiltersConfig, now: datetime
) -> FilterResult:
    """Window check first (cheapest), then the funding patterns."""
    lag = {s.name: s.lag_hours for s in sources}
    matcher = FundingMatcher(config.funding)
    result = FilterResult()
    for signal in signals:
        reason = in_window(signal, now, config.window, lag.get(signal.source, 0))
        if reason is None:
            reason = matcher.check(signal)
        if reason is None:
            result.kept.append(signal)
        else:
            result.dropped[reason] += 1
    return result
