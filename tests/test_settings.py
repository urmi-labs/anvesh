from pathlib import Path

import httpx
import pytest

from anvesh.config import ConfigError, Settings, Source, load_settings
from anvesh.http import Http, build_user_agent

EXAMPLE = Path(__file__).parent.parent / "config" / "settings.example.yaml"


def write(tmp_path, text):
    (tmp_path / "settings.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def test_missing_file_means_defaults(tmp_path):
    assert load_settings(tmp_path) == Settings()


def test_empty_file_means_defaults(tmp_path):
    assert load_settings(write(tmp_path, "# only a comment\n")) == Settings()


def test_example_file_is_valid_and_equals_defaults(tmp_path):
    assert load_settings(write(tmp_path, EXAMPLE.read_text(encoding="utf-8"))) == Settings()


def test_partial_file_keeps_other_defaults(tmp_path):
    settings = load_settings(write(tmp_path, "http:\n  timeout_seconds: 30\n"))
    assert settings.http.timeout_seconds == 30
    assert settings.http.retries == 2
    assert settings.state.retention_days == 120


def test_typo_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="timeout_secs"):
        load_settings(write(tmp_path, "http:\n  timeout_secs: 30\n"))


def test_retries_need_enough_backoffs(tmp_path):
    with pytest.raises(ConfigError, match="backoff_seconds needs at least 3"):
        load_settings(write(tmp_path, "http:\n  retries: 3\n"))


def test_google_news_uses_language():
    source = Source(name="x", adapter="google_news", query="raises", regions=["DE"])
    _, _, params = source.requests("de")[0]
    assert params["hl"] == "de-DE"
    assert params["ceid"] == "DE:de"


def test_user_agent_uses_project_url():
    agent = build_user_agent("me@example.com", "https://github.com/someone/fork")
    assert "+https://github.com/someone/fork; me@example.com" in agent


def test_http_uses_retry_settings():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    slept = []
    settings = Settings.model_validate({"http": {"retries": 1, "backoff_seconds": [7]}}).http
    client = httpx.Client(transport=httpx.MockTransport(handler))
    http = Http(client=client, user_agent="t", sleep=slept.append, clock=lambda: 0.0, settings=settings)
    assert http.get("https://example.com/").status_code == 503
    assert len(calls) == 2  # first try + 1 retry
    assert 7 in slept
