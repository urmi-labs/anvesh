"""check-sources: call every source once and report whether it works."""

import json
import os
import time
from dataclasses import dataclass

import httpx

from anvesh.config import Source, SourcesConfig
from anvesh.http import Http

FEED_MARKERS = ("<rss", "<feed", "<rdf:RDF")


@dataclass
class Result:
    label: str
    adapter: str
    verdict: str  # OK, WARN, FAIL or SKIP
    http_status: int | None = None
    size_bytes: int = 0
    items: int | None = None
    millis: int = 0
    reason: str = ""


def count_json_items(data) -> int | None:
    """Number of records in a JSON reply: the list itself, or the first list inside a dict."""
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return len(value)
    return None


def judge(source: Source, response: httpx.Response) -> tuple[str, int | None, str]:
    """Decide OK / WARN / FAIL for one reply. Returns (verdict, items, reason)."""
    if response.status_code != 200:
        return "FAIL", None, f"HTTP {response.status_code}"
    if source.adapter in ("rss", "google_news"):
        head = response.text[:2000]
        if not any(marker in head for marker in FEED_MARKERS):
            return "FAIL", None, "not an RSS or Atom feed"
        items = response.text.count("<item") + response.text.count("<entry")
        if items == 0:
            return "WARN", 0, "feed has no items"
        return "OK", items, ""
    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError):
        return "FAIL", None, "reply is not JSON"
    items = count_json_items(data)
    if items == 0:
        return "WARN", 0, "JSON has no records"
    return "OK", items, ""


def check_source(source: Source, http: Http, language: str = "en") -> list[Result]:
    missing = [name for name in source.needs if not os.environ.get(name)]
    if missing:
        return [Result(source.name, source.adapter, "SKIP", reason=f"needs {', '.join(missing)}")]
    results = []
    for label, url, params in source.requests(language):
        started = time.monotonic()
        try:
            response = http.get(url, params=params)
        except httpx.HTTPError as exc:
            millis = int((time.monotonic() - started) * 1000)
            results.append(Result(label, source.adapter, "FAIL", millis=millis, reason=type(exc).__name__))
            continue
        millis = int((time.monotonic() - started) * 1000)
        verdict, items, reason = judge(source, response)
        results.append(
            Result(label, source.adapter, verdict, response.status_code, len(response.content), items, millis, reason)
        )
    return results


def format_result(r: Result) -> str:
    status = str(r.http_status) if r.http_status else "-"
    size = f"{r.size_bytes / 1024:.0f} KB" if r.size_bytes else "-"
    items = f"{r.items} items" if r.items is not None else "-"
    line = f"{r.verdict:<5} {r.label:<26} {r.adapter:<12} {status:>4} {size:>7} {items:>11} {r.millis:>6} ms"
    return f"{line}  {r.reason}" if r.reason else line


def run_check(
    config: SourcesConfig, http: Http, include_disabled: bool = False, echo=print, language: str = "en"
) -> list[Result]:
    sources = config.sources if include_disabled else config.enabled()
    results = []
    for source in sources:
        for result in check_source(source, http, language):
            echo(format_result(result))
            results.append(result)
    counts = {v: sum(r.verdict == v for r in results) for v in ("OK", "WARN", "FAIL", "SKIP")}
    echo(
        f"\n{len(results)} checked: {counts['OK']} ok, {counts['WARN']} warn, "
        f"{counts['FAIL']} fail, {counts['SKIP']} skipped"
    )
    return results
