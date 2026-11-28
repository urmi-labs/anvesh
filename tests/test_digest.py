import httpx

from anvesh.config import DigestSettings, Settings, load_settings
from anvesh.dedupe import Story
from anvesh.digest import build_messages, story_line, visible_length
from anvesh.signals import Signal
from anvesh.telegram import Telegram

COUNTS = {"new": 3, "stories": 3, "fetched": 40, "sources": 5}


def story(title, region="IN", source="inc42", link="https://inc42.com/a", also=()):
    s = Signal(source, title, link, "Pub", None, region)
    return Story(s, [source, *also])


def test_line_hides_link_behind_escaped_title():
    line = story_line(story("Munich's R&D <AI> startup raises $5M", link="https://x.example/?a=1&b=2"), DigestSettings())
    assert line == ('• <a href="https://x.example/?a=1&amp;b=2">Munich\'s R&amp;D &lt;AI&gt; startup raises $5M</a>'
                    " · inc42")


def test_line_counts_other_sources():
    line = story_line(story("M raises $9 Mn", also=("finsmes", "gnews")), DigestSettings())
    assert line.endswith(" · inc42 +2")
    assert " · " not in story_line(story("M raises"), DigestSettings(show_sources=False))


def test_grouped_by_region_in_configured_order():
    stories = [story("A raises", "GLOBAL"), story("B raises", "IN"), story("C raises", "EU"), story("D raises", "IN")]
    [msg], held = build_messages(stories, COUNTS, DigestSettings())
    assert held == 0
    assert msg.text.startswith("<b>Anvesh: 3 newly funded startups</b>")
    order = [line for line in msg.text.splitlines() if line.startswith("<b>") and "Anvesh" not in line]
    assert order == ["<b>IN</b>", "<b>GLOBAL</b>", "<b>EU</b>"]
    assert [s.signal.title for s in msg.stories] == ["B raises", "D raises", "A raises", "C raises"]


def test_ungrouped_keeps_source_order():
    stories = [story("A raises", "GLOBAL"), story("B raises", "IN")]
    [msg], _ = build_messages(stories, COUNTS, DigestSettings(group_by_region=False))
    assert "<b>IN</b>" not in msg.text
    assert [s.signal.title for s in msg.stories] == ["A raises", "B raises"]


def test_hidden_links_do_not_count_toward_the_limit():
    stories = [story(f"Startup{i} raises $5M seed round", link=f"https://news.google.com/rss/articles/{'x' * 300}{i}")
               for i in range(40)]
    [msg], _ = build_messages(stories, COUNTS, DigestSettings())  # ~13,000 raw chars, ~1,700 visible
    assert len(msg.text) > 4096 and visible_length(msg.text) < 4096
    assert len(msg.stories) == 40


def test_visible_length_counts_like_telegram():
    assert visible_length('<b>Hi</b> <a href="https://very.long/link">A &amp; B</a>') == len("Hi A & B")
    assert visible_length("🚀") == 2  # UTF-16: an emoji is two units


def test_long_digest_splits_and_every_story_lands_in_exactly_one_message():
    stories = [story(f"Startup{i} raises a big seed round to build " + "y" * 120) for i in range(40)]
    messages, _ = build_messages(stories, COUNTS, DigestSettings())
    assert len(messages) > 1
    assert all(visible_length(m.text) <= 4096 for m in messages)
    assert sum(len(m.stories) for m in messages) == 40
    assert all(m.text.startswith("<b>IN</b>") for m in messages[1:])  # heading repeated


def test_max_stories_holds_the_rest_back():
    stories = [story(f"S{i} raises") for i in range(5)]
    [msg], held = build_messages(stories, COUNTS, DigestSettings(max_stories=2))
    assert held == 3 and len(msg.stories) == 2
    assert "3 more next run" in msg.text


def test_nothing_new_sends_nothing_unless_asked():
    assert build_messages([], COUNTS, DigestSettings()) == ([], 0)
    [msg], _ = build_messages([], {**COUNTS, "new": 0}, DigestSettings(send_when_empty=True))
    assert msg.text == "<b>Anvesh: 0 newly funded startups</b>" and msg.stories == []


def test_header_wording_is_config(tmp_path):
    (tmp_path / "settings.yaml").write_text('digest:\n  header: "{new} new / {fetched} read"\n')
    settings = load_settings(tmp_path)
    [msg], _ = build_messages([story("A raises")], COUNTS, settings.digest)
    assert msg.text.startswith("<b>3 new / 40 read</b>")
    assert load_settings(tmp_path).http == Settings().http


def test_telegram_sends_parse_mode():
    sent = []

    def handler(request):
        sent.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json={"ok": True})

    tg = Telegram("t0k", "42", client=httpx.Client(transport=httpx.MockTransport(handler)))
    tg.send("<b>hi</b>", parse_mode="HTML")
    tg.send("plain")
    tg.send("<a href=\"x\">" + "z" * 5000 + "</a>", parse_mode="HTML", split=False)
    assert sent[0]["parse_mode"] == "HTML" and "parse_mode" not in sent[1]
    assert len(sent) == 3 and sent[2]["text"].endswith("</a>")  # one message, tag intact


def test_bad_header_placeholder_is_a_config_error(tmp_path):
    import pytest

    from anvesh.config import ConfigError

    (tmp_path / "settings.yaml").write_text('digest:\n  header: "{nw} new"\n')
    with pytest.raises(ConfigError, match="unknown placeholder"):
        load_settings(tmp_path)


def test_deliver_remembers_only_what_went_out():
    from anvesh.digest import Message, deliver
    from anvesh.telegram import TelegramError

    a, b, c = story("A raises"), story("B raises"), story("C raises")
    messages = [Message("one", [a, b]), Message("two", [c])]
    sent, remembered = [], []

    def send(text):
        if text == "two":
            raise TelegramError("sendMessage failed: HTTP 429")
        sent.append(text)

    delivered, error = deliver(messages, send, remembered.append)
    assert sent == ["one"] and remembered == [a, b]
    assert delivered == 2 and isinstance(error, TelegramError)


def test_deliver_all_ok():
    from anvesh.digest import Message, deliver

    remembered = []
    delivered, error = deliver([Message("one", [story("A raises")])], lambda t: None, remembered.append)
    assert (delivered, error, len(remembered)) == (1, None, 1)
