"""Load and validate the YAML config files."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

GOOGLE_NEWS_URL = "https://news.google.com/rss/search"


class ConfigError(RuntimeError):
    """Raised when a config file is missing or invalid. The message says which field is wrong."""


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in a field name is an error, not ignored

    name: str = Field(pattern=r"^[a-z0-9_]+$")
    adapter: Literal["rss", "json_api", "google_news"]
    url: str | None = None  # rss and json_api
    query: str | None = None  # google_news
    regions: list[str] = ["IN"]  # google_news: one feed per region
    window: str = "1d"  # google_news: only stories from this period
    region: str = "GLOBAL"  # what the source covers, for reading the digest
    priority: Literal["P1", "P2", "P3"] = "P1"
    status: Literal["documented", "verified", "confirm"] = "confirm"
    enabled: bool = True
    needs: list[str] = []  # environment variables this source cannot run without
    lag_hours: int = 0  # source publishes late; added to the 24-hour limit
    min_interval_minutes: int = 0  # source's own limit on how often it may be read
    notes: str = ""

    @model_validator(mode="after")
    def check_adapter_fields(self) -> "Source":
        if self.adapter == "google_news":
            if not self.query:
                raise ValueError("google_news sources need a query")
        elif not self.url:
            raise ValueError(f"{self.adapter} sources need a url")
        return self

    def requests(self) -> list[tuple[str, str, dict | None]]:
        """Every request this source makes: (label, url, params)."""
        if self.adapter != "google_news":
            return [(self.name, self.url, None)]
        return [
            (
                f"{self.name}[{region}]",
                GOOGLE_NEWS_URL,
                {
                    "q": f"{self.query} when:{self.window}",
                    "hl": f"en-{region}",
                    "gl": region,
                    "ceid": f"{region}:en",
                },
            )
            for region in self.regions
        ]


class SourcesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[Source]

    @model_validator(mode="after")
    def names_are_unique(self) -> "SourcesConfig":
        seen = set()
        for source in self.sources:
            if source.name in seen:
                raise ValueError(f"duplicate source name: {source.name}")
            seen.add(source.name)
        return self

    def enabled(self) -> list[Source]:
        return [s for s in self.sources if s.enabled]


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"{path} not found")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must be a mapping at the top level")
    return data


def _format_errors(file_name: str, exc: ValidationError) -> str:
    lines = [f"{file_name} has {exc.error_count()} problem(s):"]
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        lines.append(f"  {location}: {error['msg']}")
    return "\n".join(lines)


def load_sources(config_dir: str | Path) -> SourcesConfig:
    path = Path(config_dir) / "sources.yaml"
    try:
        return SourcesConfig.model_validate(_read_yaml(path))
    except ValidationError as exc:
        raise ConfigError(_format_errors(path.name, exc)) from exc
