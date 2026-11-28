from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anvesh.config import ConfigError, FiltersConfig, FundingFilter, Source, WindowSettings, load_filters
from anvesh.filters import (
    EXCLUDED,
    NOT_FUNDING,
    TOO_OLD,
    UNDATED,
    FundingMatcher,
    apply_filters,
    in_window,
)
from anvesh.signals import Signal
from anvesh.state import to_iso

EXAMPLE = Path(__file__).parent.parent / "config" / "filters.example.yaml"
NOW = datetime(2026, 11, 28, 6, 0, tzinfo=UTC)


def signal(title="Acme raises $5M seed round", hours_ago=1, source="inc42", summary=""):
    published = None if hours_ago is None else to_iso(NOW - timedelta(hours=hours_ago))
    return Signal(source, title, "https://x.example/a", "Pub", published, "IN", summary)


def write(tmp_path, text):
    (tmp_path / "filters.yaml").write_text(text, encoding="utf-8")
    return tmp_path


# ---------- config ----------

def test_missing_file_means_defaults(tmp_path):
    assert load_filters(tmp_path) == FiltersConfig()


def test_example_file_is_valid_and_equals_defaults(tmp_path):
    assert load_filters(write(tmp_path, EXAMPLE.read_text(encoding="utf-8"))) == FiltersConfig()


def test_bad_regex_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="not a valid regex"):
        load_filters(write(tmp_path, "funding:\n  include: ['(unclosed']\n"))


def test_unknown_field_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="window.hourz"):
        load_filters(write(tmp_path, "window:\n  hourz: 12\n"))


def test_user_list_replaces_defaults(tmp_path):
    config = load_filters(write(tmp_path, "funding:\n  include: ['\\bgrant\\b']\n"))
    assert config.funding.include == [r"\bgrant\b"]


# ---------- window ----------

def test_recent_signal_is_kept():
    assert in_window(signal(hours_ago=23), NOW, WindowSettings()) is None


def test_old_signal_is_dropped():
    assert in_window(signal(hours_ago=25), NOW, WindowSettings()) == TOO_OLD


def test_lag_hours_widens_window():
    assert in_window(signal(hours_ago=40), NOW, WindowSettings(), lag_hours=24) is None


def test_future_date_is_kept():
    assert in_window(signal(hours_ago=-2), NOW, WindowSettings()) is None


def test_undated_keep_and_drop():
    assert in_window(signal(hours_ago=None), NOW, WindowSettings(undated="keep")) is None
    assert in_window(signal(hours_ago=None), NOW, WindowSettings(undated="drop")) == UNDATED


# ---------- funding patterns ----------

KEEP = [
    "Zepto raises $450 million in fresh funding",
    "Fintech startup Kiwi bags Rs 50 Cr in Series A round",
    "Exclusive: DevOps platform Acme secures $3M seed funding",
    "SaaS startup Beta raised $12M Series B led by Accel",
    "Gamma picks up $2M pre-seed round from angels",
    "AI startup Delta lands $8 million investment",
    "Kabeer Biswas’ M Raises $9 Mn Led By RTP Global",
    "Sqwish Labs Raises $3M in Pre-Seed Funding",
    "WaterSense Raises €5.75M in Pre-Seed Funding",
]
DROP = [
    ("Swiggy IPO opens for subscription today", EXCLUDED),
    ("Zomato acquires Blinkit in all-stock deal", EXCLUDED),
    ("Peak XV sells stake in Zomato via block deal", EXCLUDED),
    ("Edtech startup lays off 200 employees", EXCLUDED),
    ("Blume Ventures closes $290M Fund IV", EXCLUDED),
    ("Startup raises funds ahead of IPO", EXCLUDED),
    ("From Finnable To M — Indian Startups Raised About $147 Mn This Week", EXCLUDED),
    ("[Weekly funding roundup Nov 21-27] VC inflow dips on modest deal activity", EXCLUDED),
    ("Funding Galore: Indian startups raise $200 Mn", EXCLUDED),
    ("Paytm Q2 results: revenue up 10%", NOT_FUNDING),
    ("Ten tips for writing a pitch deck", NOT_FUNDING),
]


@pytest.mark.parametrize("title", KEEP)
def test_funding_titles_are_kept(title):
    assert FundingMatcher(FundingFilter()).check(signal(title)) is None


@pytest.mark.parametrize(("title", "reason"), DROP)
def test_other_titles_are_dropped(title, reason):
    assert FundingMatcher(FundingFilter()).check(signal(title)) == reason


def test_summary_only_checked_when_configured():
    s = signal("Acme's big week", summary="Acme raises $5M seed round")
    assert FundingMatcher(FundingFilter()).check(s) == NOT_FUNDING
    assert FundingMatcher(FundingFilter(match_fields=["title", "summary"])).check(s) is None


# ---------- whole pass ----------

def test_apply_filters_counts_reasons_and_uses_source_lag():
    sources = [
        Source(name="inc42", adapter="rss", url="https://inc42.com/feed/"),
        Source(name="slow", adapter="rss", url="https://slow.example/feed", lag_hours=24),
    ]
    signals = [
        signal(),                                   # kept
        signal(hours_ago=30),                       # too old for inc42
        signal(hours_ago=30, source="slow"),        # kept thanks to lag_hours
        signal("Zomato acquires Blinkit"),          # excluded
        signal("Ten tips for founders"),            # not funding
    ]
    result = apply_filters(signals, sources, FiltersConfig(), NOW)
    assert len(result.kept) == 2
    assert result.dropped == {TOO_OLD: 1, EXCLUDED: 1, NOT_FUNDING: 1}
