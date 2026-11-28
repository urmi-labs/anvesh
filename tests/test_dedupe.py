from pathlib import Path

import pytest

from anvesh.config import DedupeSettings, FiltersConfig, load_filters
from anvesh.dedupe import amounts, dedupe, name_words, normalise_link
from anvesh.signals import Signal

FIXTURE = Path(__file__).parent / "fixtures" / "funding_titles_2026-11-28.txt"
IGNORE = frozenset(DedupeSettings().ignore_words)


def sig(title, source="gnews", link=None):
    return Signal(source, title, link or f"https://x.example/{abs(hash(title))}", "Pub", None, "GLOBAL")


@pytest.mark.parametrize(("title", "expected"), [
    ("Kabeer Biswas’ M Raises $9 Mn Led By RTP Global", {("usd", 9_000_000)}),
    ("Dunzo founder's AI startup M raises $9M to automate the home", {("usd", 9_000_000)}),
    ("nextesy raises €9.48 million", {("eur", 9_480_000)}),
    ("Lakshya SmartGuard Systems Raises ₹2.5 Crore", {("inr", 25_000_000)}),
    ("Namma Yatri Raises Rs 27.25 Crore", {("inr", 272_500_000)}),
    ("Buddy Bites Raises USD 4.2 Million", {("usd", 4_200_000)}),
    ("Zippy raises $490K", {("usd", 490_000)}),
    ("On the House secures A$5.5 million", {("aud", 5_500_000)}),
    ("fintavo raises pre-seed", set()),
])
def test_amounts(title, expected):
    assert amounts(title) == expected


def test_name_words_keep_the_company():
    assert "m" in name_words("Kabeer Biswas’ M Raises $9 Mn Led By RTP Global", IGNORE)
    assert "lute" in name_words("Lute’s CEO calls touch ‘the missing signal’ as it raises $20M", IGNORE)
    assert "009" in name_words("009 Raises $1.4M in Pre-Seed Funding", IGNORE)
    assert "raises" not in name_words("Lute Raises $20M", IGNORE)


def test_normalise_link_drops_tracking_and_fragment():
    assert normalise_link("https://Inc42.com/buzz/x/?utm_source=rss&id=3#top") == "https://inc42.com/buzz/x?id=3"


def test_same_link_kept_once():
    a = sig("Acme raises $5M", "gnews", "https://news.google.com/rss/articles/abc?oc=5")
    b = sig("Acme raises $5M", "gnews", "https://news.google.com/rss/articles/abc?oc=5")
    assert len(dedupe([a, b], DedupeSettings())) == 1


def test_same_story_across_sources_merges_and_prefers_direct_link():
    stories = dedupe([
        sig("Lute Raises $20M in Funding to Develop Touch-Based AI Models for Robots", "gnews",
            "https://news.google.com/rss/articles/1"),
        sig("Lute’s CEO calls touch ‘the missing signal’ as it raises $20M", "techcrunch",
            "https://techcrunch.com/lute"),
        sig("Lute Raises $20 Million for Its Robotic Models", "finsmes"),
    ], DedupeSettings())
    assert len(stories) == 1
    assert stories[0].sources == ["gnews", "techcrunch", "finsmes"]
    assert stories[0].signal.link == "https://techcrunch.com/lute"


def test_shared_amount_without_shared_name_is_not_merged():
    stories = dedupe([sig("Sqwish Labs Raises $3M"), sig("Audun Collection Raises $3M")], DedupeSettings())
    assert len(stories) == 2


def test_amount_matching_can_be_turned_off():
    pair = [sig("Pai Defence Raises $5 Million in Pre-Seed Round"),
            sig("British-Ukrainian Defense Tech Startup Pai Defence Raises $5M for Drone Detection System")]
    assert len(dedupe(pair, DedupeSettings())) == 1
    assert len(dedupe(pair, DedupeSettings(match_on_amount=False))) == 2


def test_real_sample_from_2026_11_28():
    """46 distinct headlines from a live dry-run. Checked by hand: 33 stories, no wrong merges.
    nextesy stays split (3x) because outlets quote $10.4M, €9.48M and €9M; currencies are never converted."""
    titles = FIXTURE.read_text(encoding="utf-8").splitlines()
    stories = dedupe([sig(t) for t in titles], DedupeSettings())
    assert len(stories) == 33
    by_title = {s.signal.title: len(s.prints) for s in stories}
    # 5 headlines; inc42 and inc42_buzz are identical (same link in this test), so 4 fingerprints
    assert by_title["Kabeer Biswas’ M Raises $9 Mn Led By RTP Global"] == 4
    assert by_title["Lute Raises $20M in Funding to Develop Touch-Based AI Models for Robots"] == 3
    # every story's headlines name one company only: no two different startups were merged
    for story in stories:
        assert len({p.amounts for p in story.prints if p.amounts}) <= 2


def test_dedupe_section_in_filters_yaml(tmp_path):
    (tmp_path / "filters.yaml").write_text("dedupe:\n  title_similarity: 0.8\n  match_on_amount: false\n")
    config = load_filters(tmp_path)
    assert config.dedupe.title_similarity == 0.8 and config.dedupe.match_on_amount is False
    assert config.funding == FiltersConfig().funding


# ---------- memory across runs ----------

from datetime import UTC, datetime  # noqa: E402

from anvesh.dedupe import SeenStories  # noqa: E402
from anvesh.state import State  # noqa: E402

NOW = datetime(2026, 11, 28, 6, 0, tzinfo=UTC)


def remembered(tmp_path, *signals):
    """Deliver stories in run 1, save state, and load a fresh SeenStories as run 2 would."""
    state = State(tmp_path)
    seen = SeenStories(state.table("seen_stories"), DedupeSettings())
    for story in dedupe(list(signals), DedupeSettings()):
        seen.remember(story, now=NOW)
    state.save()
    return SeenStories(State(tmp_path).table("seen_stories"), DedupeSettings())


def test_same_link_next_run_is_seen(tmp_path):
    seen = remembered(tmp_path, sig("Acme raises $5M", "inc42", "https://inc42.com/acme"))
    [story] = dedupe([sig("Acme raises $5M", "inc42", "https://inc42.com/acme/?utm_source=x")], DedupeSettings())
    assert seen.match(story) == "https://inc42.com/acme"


def test_other_outlet_next_run_is_seen(tmp_path):
    seen = remembered(tmp_path, sig("Lute Raises $20M in Funding to Develop Touch-Based AI Models", "gnews"))
    [story] = dedupe([sig("Lute Raises $20 Million for Its Robotic Models", "finsmes")], DedupeSettings())
    assert seen.match(story) is not None


def test_new_startup_is_not_seen(tmp_path):
    seen = remembered(tmp_path, sig("Lute Raises $20M", "gnews"))
    [story] = dedupe([sig("Sooner Raises $20M in Seed Funding", "finsmes")], DedupeSettings())
    assert seen.match(story) is None


def test_record_is_readable_json(tmp_path):
    remembered(tmp_path, sig("Kabeer Biswas’ M Raises $9 Mn Led By RTP Global", "inc42", "https://inc42.com/m"))
    line = (tmp_path / "seen_stories.jsonl").read_text(encoding="utf-8")
    assert '"title": "Kabeer Biswas’ M Raises $9 Mn Led By RTP Global"' in line
    assert '"amounts": [["usd", 9000000]]' in line
