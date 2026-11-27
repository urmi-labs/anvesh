import pytest

from anvesh.config import ConfigError, load_sources


def write(tmp_path, text):
    (tmp_path / "sources.yaml").write_text(text)
    return tmp_path


def test_loads_valid_file_with_defaults(tmp_path):
    config = load_sources(write(tmp_path, """
sources:
  - {name: inc42, adapter: rss, url: "https://inc42.com/feed/", region: IN}
  - {name: paused, adapter: rss, url: "https://x.com/feed", enabled: false}
"""))
    assert [s.name for s in config.enabled()] == ["inc42"]
    assert config.sources[0].priority == "P1" and config.sources[0].status == "confirm"


def test_google_news_expands_one_request_per_region(tmp_path):
    config = load_sources(write(tmp_path, """
sources:
  - {name: gnews, adapter: google_news, query: "startup raises", regions: [IN, US]}
"""))
    requests = config.sources[0].requests()
    assert [label for label, _, _ in requests] == ["gnews[IN]", "gnews[US]"]
    params = requests[1][2]
    assert params["q"] == "startup raises when:1d" and params["gl"] == "US" and params["ceid"] == "US:en"


def test_rss_without_url_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="rss sources need a url"):
        load_sources(write(tmp_path, "sources:\n  - {name: bad, adapter: rss}\n"))


def test_unknown_field_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="enabeld"):
        load_sources(write(tmp_path, 'sources:\n  - {name: a, adapter: rss, url: "u", enabeld: false}\n'))


def test_unknown_adapter_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="adapter"):
        load_sources(write(tmp_path, 'sources:\n  - {name: a, adapter: ftp, url: "u"}\n'))


def test_duplicate_names_are_rejected(tmp_path):
    with pytest.raises(ConfigError, match="duplicate source name: a"):
        load_sources(write(tmp_path, 'sources:\n  - {name: a, adapter: rss, url: "u"}\n  - {name: a, adapter: rss, url: "v"}\n'))


def test_missing_file_and_bad_yaml(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_sources(tmp_path)
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_sources(write(tmp_path, "sources: [unclosed\n"))


def test_example_file_is_valid(tmp_path):
    from pathlib import Path

    example = Path(__file__).parent.parent / "config" / "sources.example.yaml"
    (tmp_path / "sources.yaml").write_text(example.read_text())
    config = load_sources(tmp_path)
    assert len(config.sources) >= 20
