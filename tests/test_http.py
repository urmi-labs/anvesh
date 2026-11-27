import httpx
import pytest

from anvesh.http import Http, build_user_agent
from anvesh.state import Table


class FakeTime:
    """A clock that only moves when the code under test sleeps."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(round(seconds, 2))
        self.now += seconds

    def clock(self):
        return self.now


def make_http(handler, cache=None):
    fake = FakeTime()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    http = Http(cache=cache, client=client, user_agent="test-agent", sleep=fake.sleep, clock=fake.clock)
    return http, fake


def test_user_agent_includes_contact():
    assert build_user_agent("me@example.com").endswith("; me@example.com)")
    assert "me@" not in build_user_agent("")


def test_sends_user_agent():
    seen = []

    def handler(request):
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200)

    http, _ = make_http(handler)
    http.get("https://example.com/feed")
    assert seen == ["test-agent"]


def test_same_host_waits_one_second_other_host_does_not():
    http, fake = make_http(lambda request: httpx.Response(200))
    http.get("https://a.com/1")
    http.get("https://b.com/1")
    assert fake.slept == []
    http.get("https://a.com/2")
    assert fake.slept == [1.0]


def test_retries_5xx_then_succeeds():
    statuses = iter([503, 200])
    http, fake = make_http(lambda request: httpx.Response(next(statuses)))
    assert http.get("https://example.com").status_code == 200
    assert 2 in fake.slept  # first backoff


def test_honours_retry_after_but_caps_it():
    statuses = iter([(429, {"Retry-After": "600"}), (200, {})])

    def handler(request):
        status, headers = next(statuses)
        return httpx.Response(status, headers=headers)

    http, fake = make_http(handler)
    http.get("https://example.com")
    assert 30 in fake.slept


def test_gives_up_after_retries_and_returns_last_response():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500)

    http, _ = make_http(handler)
    assert http.get("https://example.com").status_code == 500
    assert len(calls) == 3


def test_404_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404)

    http, _ = make_http(handler)
    assert http.get("https://example.com").status_code == 404
    assert len(calls) == 1


def test_connection_error_raises_after_retries():
    def handler(request):
        raise httpx.ConnectError("down")

    http, _ = make_http(handler)
    with pytest.raises(httpx.ConnectError):
        http.get("https://example.com")


def test_conditional_get_sends_saved_etag_and_gets_304(tmp_path):
    cache = Table(tmp_path / "http_cache.jsonl")
    sent = []

    def handler(request):
        sent.append(request.headers.get("If-None-Match"))
        if request.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, headers={"ETag": '"v1"'}, text="feed")

    http, _ = make_http(handler, cache=cache)
    assert http.get("https://example.com/feed", conditional=True).status_code == 200
    assert http.get("https://example.com/feed", conditional=True).status_code == 304
    assert sent == [None, '"v1"']
