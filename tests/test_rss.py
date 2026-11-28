import httpx
import pytest

from anvesh.adapters import SourceError, fetch
from anvesh.adapters.base import clean_text
from anvesh.adapters.rss import parse_feed
from anvesh.config import Source
from anvesh.http import Http
from anvesh.state import Table

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Inc42 Media</title>
<item>
  <title>Acme raises $5 Mn in Series A led by Peak XV</title>
  <link>https://inc42.com/buzz/acme-raises/</link>
  <pubDate>Fri, 27 Nov 2026 09:30:00 +0530</pubDate>
  <description><![CDATA[<p>Acme, a <b>DevTools</b> startup &amp; more</p>]]></description>
</item>
<item><title>No date here</title><link>https://inc42.com/x/</link></item>
<item><title></title><link>https://inc42.com/empty-title/</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom Blog</title>
<entry><title>Beta raises seed</title><link href="https://blog.example/beta"/>
<updated>2026-11-27T04:00:00Z</updated></entry></feed>"""

GOOGLE = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>"raises" - Google News</title>
<item>
  <title>Gamma bags $10M seed round - Entrackr</title>
  <link>https://news.google.com/rss/articles/abc</link>
  <pubDate>Fri, 27 Nov 2026 06:00:00 GMT</pubDate>
  <description>&lt;a href="x"&gt;Gamma bags&lt;/a&gt; Entrackr</description>
  <source url="https://entrackr.com">Entrackr</source>
</item></channel></rss>"""

RSS_SOURCE = Source(name="inc42", adapter="rss", url="https://inc42.com/feed/", region="IN")
GN_SOURCE = Source(name="entrackr", adapter="google_news", query="site:entrackr.com raises", regions=["IN"])


def make_http(handler, cache=None):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Http(cache=cache, client=client, user_agent="t", sleep=lambda s: None, clock=lambda: 0.0)


def test_clean_text_strips_html_and_spaces():
    assert clean_text("<p>Acme &amp;  <b>Co</b></p>\n") == "Acme & Co"
    assert clean_text(None) == ""


def test_rss_becomes_signals():
    signals = parse_feed(RSS_SOURCE, RSS)
    assert len(signals) == 2  # the empty-title item is skipped
    first = signals[0]
    assert first.title == "Acme raises $5 Mn in Series A led by Peak XV"
    assert first.publisher == "Inc42 Media"
    assert first.published == "2026-11-27T04:00:00Z"  # 09:30 IST converted to UTC
    assert first.region == "IN" and first.source == "inc42"
    assert first.summary == "Acme, a DevTools startup & more"
    assert signals[1].published is None


def test_atom_feed_uses_updated_date():
    [signal] = parse_feed(RSS_SOURCE, ATOM)
    assert signal.link == "https://blog.example/beta"
    assert signal.published == "2026-11-27T04:00:00Z"


def test_google_news_publisher_and_title():
    [signal] = parse_feed(GN_SOURCE, GOOGLE)
    assert signal.publisher == "Entrackr"
    assert signal.title == "Gamma bags $10M seed round"
    assert signal.summary == ""


def test_html_page_is_an_error():
    with pytest.raises(SourceError, match="not a valid feed"):
        parse_feed(RSS_SOURCE, b"<html><body>Access denied</body></html>")


def test_fetch_uses_etag_and_304_gives_nothing(tmp_path):
    def handler(request):
        if request.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=RSS, headers={"ETag": '"v1"'})

    http = make_http(handler, cache=Table(tmp_path / "http_cache.jsonl"))
    assert len(fetch(RSS_SOURCE, http)) == 2
    assert fetch(RSS_SOURCE, http) == []


def test_bad_status_is_a_source_error():
    http = make_http(lambda request: httpx.Response(403))
    with pytest.raises(SourceError, match="HTTP 403"):
        fetch(RSS_SOURCE, http)


def test_empty_feed_is_not_an_error():
    empty = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
    assert parse_feed(RSS_SOURCE, empty) == []
