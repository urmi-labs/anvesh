"""One radar pass: fetch every enabled source, then pre-filter what came back.

Later steps (dedupe, digest) plug in after filter. A broken source never stops
the run: its error is recorded and the other sources still run.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime

from anvesh.adapters import IMPLEMENTED, SourceError, fetch
from anvesh.dedupe import SeenStories, Story, dedupe
from anvesh.config import FiltersConfig, SourcesConfig
from anvesh.filters import FilterResult, apply_filters
from anvesh.http import Http
from anvesh.signals import Signal


@dataclass
class Collected:
    signals: list[Signal] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)  # source name -> error
    skipped: dict[str, str] = field(default_factory=dict)  # source name -> why


def collect(sources: SourcesConfig, http: Http, language: str = "en") -> Collected:
    """Fetch every enabled source.

    Skipped (not failed): sources missing a needed env var, and sources whose adapter
    is not built yet. "failed" is kept for real breakage, so it stays worth reading.
    """
    out = Collected()
    for source in sources.enabled():
        if source.adapter not in IMPLEMENTED:
            out.skipped[source.name] = f"adapter '{source.adapter}' not built yet"
            continue
        missing = [name for name in source.needs if not os.environ.get(name)]
        if missing:
            out.skipped[source.name] = f"needs {', '.join(missing)}"
            continue
        try:
            out.signals.extend(fetch(source, http, language))
        except SourceError as exc:
            out.failed[source.name] = str(exc)
    return out


@dataclass
class Pass:
    """Everything one run found, step by step."""

    collected: Collected
    filtered: FilterResult
    stories: list[Story]  # after dedupe
    new: list[Story]  # not delivered in an earlier run
    already_seen: int


def run_pass(
    sources: SourcesConfig,
    filters: FiltersConfig,
    http: Http,
    now: datetime,
    seen: SeenStories | None = None,
    language: str = "en",
) -> Pass:
    """fetch -> 24h + funding filter -> dedupe -> drop stories delivered before."""
    collected = collect(sources, http, language)
    filtered = apply_filters(collected.signals, sources.sources, filters, now)
    stories = dedupe(filtered.kept, filters.dedupe)
    new = [s for s in stories if seen is None or seen.match(s) is None]
    return Pass(collected, filtered, stories, new, len(stories) - len(new))


def summary_line(p: Pass) -> str:
    """e.g. 'fetched 467 signals from 16 sources (0 failed, 8 skipped); kept 115; dropped ...;
    33 stories (30 new, 3 already seen)'"""
    collected, result = p.collected, p.filtered
    ok = len({s.source for s in collected.signals})
    drops = " ".join(f"{reason}={n}" for reason, n in sorted(result.dropped.items())) or "none"
    return (
        f"fetched {len(collected.signals)} signals from {ok} sources "
        f"({len(collected.failed)} failed, {len(collected.skipped)} skipped); "
        f"kept {len(result.kept)}; dropped {drops}; "
        f"{len(p.stories)} stories ({len(p.new)} new, {p.already_seen} already seen)"
    )
