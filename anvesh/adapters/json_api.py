"""JSON APIs (job boards, Hacker News search). One generic adapter driven by sources.yaml:

    items: jobs                 # dotted path to the list of records; "" when the reply IS the list
    fields:
      title: jobTitle           # the API's own key names
      company: companyName
      link: url                 # or link_template: "https://news.ycombinator.com/item?id={objectID}"
      published: pubDate        # the POSTED date. Never map an updated/modified field here.
      summary: jobExcerpt

Records that are not objects or have no title/link are skipped (Remote OK's first record is a
legal notice). Dates: ISO 8601, RFC 2822, or Unix seconds/milliseconds; read as UTC; a date that
cannot be parsed or is more than 1 hour in the future is treated as missing (design: hard rules).
"""

import json
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx

from anvesh.adapters.base import SourceError, clean_text
from anvesh.config import Source
from anvesh.http import Http
from anvesh.signals import Signal
from anvesh.state import to_iso, utc_now

SUMMARY_CHARS = 600  # job descriptions are long HTML; keep the start for later filters
FUTURE_TOLERANCE = timedelta(hours=1)


def dig(data, path: str):
    """Follow a dotted path: dig({"a": {"b": [1]}}, "a.b") -> [1]. "" returns data itself."""
    for part in [p for p in path.split(".") if p]:
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def parse_date(value, now: datetime | None = None) -> str | None:
    """Any common API date -> UTC ISO string, or None if missing, unreadable or in the future."""
    if value in (None, "", 0):
        return None
    moment = None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        number = float(value)
        if number > 1e12:  # milliseconds
            number /= 1000
        moment = datetime.fromtimestamp(number, UTC)
    elif isinstance(value, str):
        text = value.strip()
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                moment = parsedate_to_datetime(text)
            except (TypeError, ValueError):
                return None
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)  # no zone given: the APIs we use publish UTC
    if moment - (now or utc_now()) > FUTURE_TOLERANCE:
        return None
    return to_iso(moment)


def _text(record: dict, key: str | None) -> str:
    if not key:
        return ""
    value = dig(record, key)
    return clean_text(value if isinstance(value, str) else "" if value is None else str(value))


def parse_records(source: Source, data, now: datetime | None = None) -> list[Signal]:
    records = dig(data, source.items)
    if not isinstance(records, list):
        raise SourceError(f"{source.name}: no list at items path '{source.items}'")
    f = source.fields
    signals = []
    for record in records:
        if not isinstance(record, dict):
            continue
        title = _text(record, f.title)
        link = _text(record, f.link)
        if not link and f.link_template:
            try:
                link = f.link_template.format_map({k: v for k, v in record.items() if v is not None})
            except (KeyError, ValueError):
                link = ""
        if not title or not link:
            continue
        signals.append(
            Signal(
                source=source.name,
                title=title,
                link=link,
                publisher=source.name,
                published=parse_date(dig(record, f.published), now) if f.published else None,
                region=source.region,
                summary=_text(record, f.summary)[:SUMMARY_CHARS],
                kind=source.kind,
                company=_text(record, f.company),
            )
        )
    return signals


def fetch_json(source: Source, http: Http) -> list[Signal]:
    try:
        response = http.get(source.url, conditional=True)
    except httpx.HTTPError as exc:
        raise SourceError(f"{source.name}: {type(exc).__name__}") from exc
    if response.status_code == 304:
        return []
    if response.status_code != 200:
        raise SourceError(f"{source.name}: HTTP {response.status_code}")
    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise SourceError(f"{source.name}: reply is not JSON") from exc
    return parse_records(source, data)
