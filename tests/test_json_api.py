"""json_api adapter, with replies shaped like the real APIs (trimmed)."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from anvesh.adapters import SourceError, fetch
from anvesh.adapters.json_api import dig, parse_date, parse_records
from anvesh.config import ConfigError, Source, load_sources
from anvesh.http import Http

NOW = datetime(2026, 11, 28, 6, 0, tzinfo=UTC)
EXAMPLE = Path(__file__).parent.parent / "config" / "sources.example.yaml"


def example_source(name: str) -> Source:
    config_dir = Path(__file__).parent.parent / "config"
    import shutil
    import tempfile

    d = tempfile.mkdtemp()
    shutil.copy(EXAMPLE, Path(d) / "sources.yaml")
    return next(s for s in load_sources(d).sources if s.name == name)


REMOTEOK = [
    {"legal": "API Terms of Service: please link back to Remote OK"},
    {"id": "1", "position": "Junior DevOps Engineer", "company": "Acme", "url": "https://remoteok.com/remote-jobs/1",
     "date": "2026-11-27T14:00:09+00:00", "epoch": 1795874409, "description": "<p>Kubernetes &amp; AWS</p>"},
]
JOBICY = {"jobs": [{"jobTitle": "Site Reliability Engineer", "companyName": "Beta", "url": "https://jobicy.com/jobs/2",
                    "pubDate": "2026-11-28 03:10:00", "jobExcerpt": "Run our infra"}]}
ARBEITNOW = {"data": [{"title": "Platform Engineer", "company_name": "Gamma GmbH", "url": "https://arbeitnow.com/3",
                       "created_at": 1795840000, "description": "<b>Terraform</b>"}],
             "links": {"next": "https://www.arbeitnow.com/api/job-board-api?page=2"}}
HN = {"hits": [{"title": "Delta (YC S24) Is Hiring a DevOps Engineer", "url": None, "objectID": "424242",
                "created_at": "2026-11-28T02:00:00Z", "story_text": "We run on <i>k8s</i>"}]}


@pytest.mark.parametrize(("name", "data", "title", "company", "link", "published"), [
    ("remoteok", REMOTEOK, "Junior DevOps Engineer", "Acme", "https://remoteok.com/remote-jobs/1", "2026-11-27T14:00:09Z"),
    ("jobicy", JOBICY, "Site Reliability Engineer", "Beta", "https://jobicy.com/jobs/2", "2026-11-28T03:10:00Z"),
    ("arbeitnow", ARBEITNOW, "Platform Engineer", "Gamma GmbH", "https://arbeitnow.com/3", "2026-11-28T04:26:40Z"),
    ("hn_jobs", HN, "Delta (YC S24) Is Hiring a DevOps Engineer", "", "https://news.ycombinator.com/item?id=424242",
     "2026-11-28T02:00:00Z"),
])
def test_example_mappings_parse_real_shapes(name, data, title, company, link, published):
    source = example_source(name)
    [signal] = parse_records(source, data, now=NOW)
    assert (signal.title, signal.company, signal.link, signal.published) == (title, company, link, published)
    assert signal.kind == "job" and signal.source == name
    assert "<" not in signal.summary


def test_launch_kind_and_hn_link_template():
    source = example_source("hn_launches")
    [signal] = parse_records(source, {"hits": [{"title": "Launch HN: Epsilon (YC F25) – GPU autoscaling",
                                                 "objectID": "7", "created_at": "2026-11-28T01:00:00Z"}]}, now=NOW)
    assert signal.kind == "launch" and signal.link == "https://news.ycombinator.com/item?id=7"


@pytest.mark.parametrize(("value", "expected"), [
    ("2026-11-28T02:00:00Z", "2026-11-28T02:00:00Z"),
    ("2026-11-28T07:30:00+05:30", "2026-11-28T02:00:00Z"),
    ("2026-11-28 02:00:00", "2026-11-28T02:00:00Z"),  # no zone: UTC
    ("Sat, 28 Nov 2026 02:00:00 GMT", "2026-11-28T02:00:00Z"),
    (1795831200, "2026-11-28T02:00:00Z"),
    ("1795831200", "2026-11-28T02:00:00Z"),
    (1795831200000, "2026-11-28T02:00:00Z"),  # milliseconds
    ("2026-11-28T08:00:00Z", None),  # 2h in the future: treated as missing
    ("yesterday-ish", None),
    (None, None),
    ("", None),
])
def test_parse_date(value, expected):
    assert parse_date(value, NOW) == expected


def test_dig():
    assert dig({"a": {"b": [1]}}, "a.b") == [1]
    assert dig([1, 2], "") == [1, 2]
    assert dig({"a": 1}, "x") is None


def test_records_without_title_or_link_are_skipped():
    source = Source(name="x", adapter="json_api", url="https://x", kind="job", items="jobs",
                    fields={"title": "t", "link": "u"})
    data = {"jobs": [{"t": "A", "u": "https://x/1"}, {"t": "", "u": "https://x/2"}, {"t": "C"}, "junk", None]}
    assert [s.title for s in parse_records(source, data, now=NOW)] == ["A"]


def test_wrong_items_path_is_a_source_error():
    source = Source(name="x", adapter="json_api", url="https://x", items="jobs", fields={"title": "t", "link": "u"})
    with pytest.raises(SourceError, match="no list at items path 'jobs'"):
        parse_records(source, {"data": []}, now=NOW)


def test_fetch_json_errors_and_304():
    source = Source(name="x", adapter="json_api", url="https://x.example/api", fields={"title": "t", "link": "u"})

    def http(response):
        client = httpx.Client(transport=httpx.MockTransport(lambda r: response))
        return Http(client=client, user_agent="t", sleep=lambda s: None)

    with pytest.raises(SourceError, match="HTTP 403"):
        fetch(source, http(httpx.Response(403)))
    with pytest.raises(SourceError, match="not JSON"):
        fetch(source, http(httpx.Response(200, text="<html>")))
    assert fetch(source, http(httpx.Response(304))) == []
    assert len(fetch(source, http(httpx.Response(200, json=[{"t": "A", "u": "https://x/1"}])))) == 1


def test_enabled_json_api_needs_fields(tmp_path):
    (tmp_path / "sources.yaml").write_text("sources:\n  - name: x\n    adapter: json_api\n    url: https://x\n")
    with pytest.raises(ConfigError, match="need `fields`"):
        load_sources(tmp_path)
    (tmp_path / "sources.yaml").write_text(
        "sources:\n  - name: x\n    adapter: json_api\n    url: https://x\n    fields: {title: t}\n")
    with pytest.raises(ConfigError, match="link or link_template"):
        load_sources(tmp_path)
