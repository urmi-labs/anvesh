from pathlib import Path

import pytest

from anvesh.config import ConfigError, DedupeSettings, FiltersConfig, FundingFilter, SectorFilter, load_filters
from anvesh.dedupe import dedupe
from anvesh.filters import EXCLUDED, FundingMatcher
from anvesh.sector import NON_TECH, TECH, UNKNOWN, SectorClassifier, filter_sector
from anvesh.signals import Signal

FIXTURE = Path(__file__).parent / "fixtures" / "funding_titles_2026-11-28.txt"


def sig(title, summary="", n=0):
    return Signal("gnews", title, f"https://x.example/{n}-{abs(hash(title))}", "Pub", None, "GLOBAL", summary)


def stories(*titles):
    return dedupe([sig(t, n=i) for i, t in enumerate(titles)], DedupeSettings())


@pytest.mark.parametrize(("title", "label"), [
    ("Reversa raises €750K to develop AI agents for regulatory compliance", TECH),
    ("London startup Sequent raises $2.2m for software safety verification", TECH),
    ("Buddy Bites Raises USD 4.2 Million For Regional Pet Food Growth", NON_TECH),
    ("UK Plant-Based Protein Water Startup Nowhey Bags Pre-Seed Funding for Expansion", NON_TECH),
    ("Free period products startup On the House secures A$5.5 million funding", NON_TECH),
    ("Sooner Raises $20M in Seed Funding", UNKNOWN),
    ("WaterSense Raises €5.75M in Pre-Seed Funding", UNKNOWN),  # "water" inside a name is not a drink
    ("Snackly raises $4M for its AI food ordering app", TECH),  # tech wins over non-tech
])
def test_classify(title, label):
    [story] = stories(title)
    assert SectorClassifier(SectorFilter()).classify(story) == label


def test_merged_headlines_decide_together():
    [story] = stories("Lampsy Health Raises €1.1M in Funding",
                      "Lisbon’s Lampsy Health raises €1.1 million for its AI bedside lamp")
    assert SectorClassifier(SectorFilter()).classify(story) == TECH


def test_summary_counts_unless_turned_off():
    [story] = dedupe([sig("Sooner Raises $20M", summary="Sooner builds data infrastructure for banks")],
                     DedupeSettings())
    assert SectorClassifier(SectorFilter()).classify(story) == TECH
    assert SectorClassifier(SectorFilter(match_fields=["title"])).classify(story) == UNKNOWN


def test_unknown_keep_or_drop_and_disable():
    found = stories("Sooner Raises $20M", "Buddy Bites Raises $4M For Pet Food", "Lute Raises $20M for robots")
    kept = filter_sector(found, SectorFilter())
    assert [s.signal.title for s in kept.dropped] == ["Buddy Bites Raises $4M For Pet Food"]
    assert len(kept.kept) == 2 and kept.unknown == 1
    strict = filter_sector(found, SectorFilter(unknown="drop"))
    assert [s.signal.title for s in strict.kept] == ["Lute Raises $20M for robots"]
    assert len(filter_sector(found, SectorFilter(enabled=False)).kept) == 3


def test_real_sample_drops_exactly_the_three_non_tech_raises():
    titles = FIXTURE.read_text(encoding="utf-8").splitlines()
    result = filter_sector(dedupe([sig(t, n=i) for i, t in enumerate(titles)], DedupeSettings()), SectorFilter())
    assert sorted(s.signal.title for s in result.dropped) == [
        "Buddy Bites Raises USD 4.2 Million For Regional Pet Food Growth",
        "Free period products startup On the House secures A$5.5 million funding",
        "UK Plant-Based Protein Water Startup Nowhey Bags Pre-Seed Funding for Expansion",
    ]


def test_government_grant_is_not_a_funding_round():
    title = "Ludhiana: Vet varsity startup secures govt seed funding"
    assert FundingMatcher(FundingFilter()).check(sig(title)) == EXCLUDED


def test_sector_config(tmp_path):
    (tmp_path / "filters.yaml").write_text("sector:\n  unknown: drop\n  non_tech: ['\\bfood\\b']\n")
    config = load_filters(tmp_path)
    assert config.sector.unknown == "drop" and config.sector.non_tech == [r"\bfood\b"]
    assert config.sector.tech == FiltersConfig().sector.tech
    (tmp_path / "filters.yaml").write_text("sector:\n  tech: ['(broken']\n")
    with pytest.raises(ConfigError, match="tech pattern"):
        load_filters(tmp_path)
