import httpx

from anvesh.check import count_json_items, run_check
from anvesh.config import SourcesConfig
from anvesh.http import Http

FIELDS = {"title": "title", "link": "url"}
RSS = '<?xml version="1.0"?><rss><channel><item>a</item><item>b</item></channel></rss>'
EMPTY_RSS = '<?xml version="1.0"?><rss><channel></channel></rss>'


def make_config(*sources):
    return SourcesConfig.model_validate({"sources": list(sources)})


def make_http(routes):
    def handler(request):
        status, body = routes[request.url.host]
        return httpx.Response(status, text=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Http(client=client, user_agent="test", sleep=lambda s: None)


def test_verdicts_for_each_kind_of_reply(monkeypatch):
    monkeypatch.delenv("RADAR_CONTACT", raising=False)
    config = make_config(
        {"name": "good_feed", "adapter": "rss", "url": "https://good.com/feed"},
        {"name": "empty_feed", "adapter": "rss", "url": "https://empty.com/feed"},
        {"name": "html_page", "adapter": "rss", "url": "https://html.com/feed"},
        {"name": "gone", "adapter": "rss", "url": "https://gone.com/feed"},
        {"name": "good_api", "adapter": "json_api", "url": "https://api.com/jobs", "fields": FIELDS},
        {"name": "bad_api", "adapter": "json_api", "url": "https://bad.com/jobs", "fields": FIELDS},
        {"name": "sec", "adapter": "json_api", "url": "https://sec.gov/x", "needs": ["RADAR_CONTACT"], "fields": FIELDS},
        {"name": "paused", "adapter": "rss", "url": "https://good.com/feed", "enabled": False},
    )
    http = make_http(
        {
            "good.com": (200, RSS),
            "empty.com": (200, EMPTY_RSS),
            "html.com": (200, "<html><body>Not a feed</body></html>"),
            "gone.com": (404, "missing"),
            "api.com": (200, '{"jobs": [{"id": 1}, {"id": 2}, {"id": 3}]}'),
            "bad.com": (200, "<html>oops</html>"),
        }
    )
    lines = []
    results = run_check(config, http, echo=lines.append)
    verdicts = {r.label: (r.verdict, r.items, r.reason) for r in results}
    assert verdicts == {
        "good_feed": ("OK", 2, ""),
        "empty_feed": ("WARN", 0, "feed has no items"),
        "html_page": ("FAIL", None, "not an RSS or Atom feed"),
        "gone": ("FAIL", None, "HTTP 404"),
        "good_api": ("OK", 3, ""),
        "bad_api": ("FAIL", None, "reply is not JSON"),
        "sec": ("SKIP", None, "needs RADAR_CONTACT"),
    }
    assert "paused" not in verdicts
    assert lines[-1].endswith("7 checked: 2 ok, 1 warn, 3 fail, 1 skipped")


def test_include_disabled():
    config = make_config({"name": "paused", "adapter": "rss", "url": "https://good.com/feed", "enabled": False})
    results = run_check(config, make_http({"good.com": (200, RSS)}), include_disabled=True, echo=lambda s: None)
    assert [r.label for r in results] == ["paused"]


def test_connection_error_is_a_fail_not_a_crash():
    def handler(request):
        raise httpx.ConnectError("down")

    http = Http(client=httpx.Client(transport=httpx.MockTransport(handler)), user_agent="t", sleep=lambda s: None)
    config = make_config({"name": "down", "adapter": "rss", "url": "https://down.com/feed"})
    [result] = run_check(config, http, echo=lambda s: None)
    assert result.verdict == "FAIL" and result.reason == "ConnectError"


def test_count_json_items():
    assert count_json_items([1, 2]) == 2
    assert count_json_items({"meta": {}, "data": [1, 2, 3]}) == 3
    assert count_json_items({"total": 5}) is None
