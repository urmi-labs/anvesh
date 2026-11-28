"""Whole `anvesh run` twice, offline: fake sources (MockTransport) and a fake Telegram."""

from datetime import UTC, datetime

import httpx

import anvesh.__main__ as cli
from anvesh.http import Http

NOW = datetime(2026, 11, 28, 6, 0, tzinfo=UTC)
FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
<item><title>Acme raises $5M seed round</title><link>https://a.example/1</link>
<pubDate>Sat, 28 Nov 2026 04:00:00 GMT</pubDate></item>
<item><title>Zomato acquires Blinkit</title><link>https://a.example/2</link>
<pubDate>Sat, 28 Nov 2026 04:00:00 GMT</pubDate></item>
</channel></rss>"""


class FakeTelegram:
    sent: list[tuple[str, str | None]] = []

    @classmethod
    def from_env(cls):
        return cls()

    def send(self, text, parse_mode=None, split=True):
        FakeTelegram.sent.append((text, parse_mode))


def setup(monkeypatch, tmp_path):
    (tmp_path / "sources.yaml").write_text(
        "sources:\n  - name: good\n    adapter: rss\n    url: https://good.example/feed\n    region: IN\n"
    )
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=FEED.encode())))
    real_http = Http
    monkeypatch.setattr(cli, "Http", lambda **kw: real_http(client=client, user_agent="t", sleep=lambda s: None, **kw))
    monkeypatch.setattr(cli, "Telegram", FakeTelegram)
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    FakeTelegram.sent = []


def test_run_delivers_once_then_remembers(monkeypatch, tmp_path, capsys):
    setup(monkeypatch, tmp_path)
    args = ["run", "--config", str(tmp_path), "--state-dir", str(tmp_path / "state")]

    assert cli.main(args) == 0
    [(text, mode)] = FakeTelegram.sent
    assert mode == "HTML"
    assert '<a href="https://a.example/1">Acme raises $5M seed round</a>' in text
    assert "Zomato" not in text
    assert "Acme raises" in (tmp_path / "state" / "seen_stories.jsonl").read_text()

    assert cli.main(args) == 0  # second run: same feed, nothing new, nothing sent
    assert len(FakeTelegram.sent) == 1
    out = capsys.readouterr().out
    assert "1 stories (0 new, 1 already seen)" in out and out.rstrip().endswith("nothing new, nothing sent")


def test_dry_run_prints_digest_and_writes_nothing(monkeypatch, tmp_path, capsys):
    setup(monkeypatch, tmp_path)
    assert cli.main(["dry-run", "--config", str(tmp_path), "--state-dir", str(tmp_path / "state")]) == 0
    out = capsys.readouterr().out
    assert "[dry-run] message 1/1" in out and "Acme raises $5M seed round" in out
    assert FakeTelegram.sent == []
    assert not (tmp_path / "state").exists()
