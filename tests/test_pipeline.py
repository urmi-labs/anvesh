from datetime import UTC, datetime

import httpx

from anvesh.config import FiltersConfig, SourcesConfig
from anvesh.http import Http
from anvesh.pipeline import run_pass, summary_line

NOW = datetime(2026, 11, 28, 6, 0, tzinfo=UTC)
FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
<item><title>Acme raises $5M seed round</title><link>https://a.example/1</link>
<pubDate>Sat, 28 Nov 2026 04:00:00 GMT</pubDate></item>
<item><title>Zomato acquires Blinkit</title><link>https://a.example/2</link>
<pubDate>Sat, 28 Nov 2026 04:00:00 GMT</pubDate></item>
<item><title>Beta raises $9M Series A</title><link>https://a.example/3</link>
<pubDate>Mon, 23 Nov 2026 04:00:00 GMT</pubDate></item>
</channel></rss>"""


def make_http():
    def handler(request):
        if request.url.host == "good.example":
            return httpx.Response(200, content=FEED.encode())
        return httpx.Response(403, text="<html>blocked</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Http(client=client, user_agent="test", sleep=lambda s: None)


def test_run_pass_keeps_fresh_funding_and_survives_broken_sources(monkeypatch):
    monkeypatch.delenv("SOME_KEY", raising=False)
    sources = SourcesConfig.model_validate({"sources": [
        {"name": "good", "adapter": "rss", "url": "https://good.example/feed"},
        {"name": "blocked", "adapter": "rss", "url": "https://blocked.example/feed"},
        {"name": "keyed", "adapter": "rss", "url": "https://good.example/k", "needs": ["SOME_KEY"]},
        {"name": "off", "adapter": "rss", "url": "https://good.example/off", "enabled": False},
        {"name": "api", "adapter": "json_api", "url": "https://good.example/api"},
    ]})
    collected, result = run_pass(sources, FiltersConfig(), make_http(), NOW)
    assert [s.title for s in result.kept] == ["Acme raises $5M seed round"]
    assert dict(result.dropped) == {"excluded": 1, "too_old": 1}
    assert collected.failed == {"blocked": "blocked: HTTP 403"}
    assert collected.skipped == {"keyed": "needs SOME_KEY", "api": "adapter 'json_api' not built yet"}
    line = summary_line(collected, result)
    assert "fetched 3 signals from 1 sources (1 failed, 2 skipped); kept 1" in line
