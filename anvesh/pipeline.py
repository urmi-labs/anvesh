"""One radar pass: fetch every enabled source, then pre-filter what came back.

Later steps (dedupe, digest) plug in after filter. A broken source never stops
the run: its error is recorded and the other sources still run.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime

from anvesh.adapters import SourceError, fetch
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
    """Fetch every enabled source. Sources missing a needed env var are skipped, not failed."""
    out = Collected()
    for source in sources.enabled():
        missing = [name for name in source.needs if not os.environ.get(name)]
        if missing:
            out.skipped[source.name] = f"needs {', '.join(missing)}"
            continue
        try:
            out.signals.extend(fetch(source, http, language))
        except SourceError as exc:
            out.failed[source.name] = str(exc)
    return out


def run_pass(
    sources: SourcesConfig, filters: FiltersConfig, http: Http, now: datetime, language: str = "en"
) -> tuple[Collected, FilterResult]:
    collected = collect(sources, http, language)
    return collected, apply_filters(collected.signals, sources.sources, filters, now)


def summary_line(collected: Collected, result: FilterResult) -> str:
    """e.g. 'fetched 108 from 26 sources (1 failed, 1 skipped); kept 10; dropped too_old=46 ...'"""
    ok = len({s.source for s in collected.signals})
    drops = " ".join(f"{reason}={n}" for reason, n in sorted(result.dropped.items())) or "none"
    return (
        f"fetched {len(collected.signals)} signals from {ok} sources "
        f"({len(collected.failed)} failed, {len(collected.skipped)} skipped); "
        f"kept {len(result.kept)}; dropped {drops}"
    )
