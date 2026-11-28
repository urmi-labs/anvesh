"""Load and validate the YAML config files."""

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

GOOGLE_NEWS_URL = "https://news.google.com/rss/search"


class ConfigError(RuntimeError):
    """Raised when a config file is missing or invalid. The message says which field is wrong."""


class JsonFields(BaseModel):
    """json_api: which field of each record holds what. Names are the API's own keys."""

    model_config = ConfigDict(extra="forbid")

    title: str
    link: str | None = None
    link_template: str | None = None  # e.g. "https://news.ycombinator.com/item?id={objectID}"
    company: str | None = None
    published: str | None = None  # the POSTED / created date; never an updated/modified field
    summary: str | None = None

    @model_validator(mode="after")
    def has_a_link(self) -> "JsonFields":
        if not self.link and not self.link_template:
            raise ValueError("fields need link or link_template")
        return self


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in a field name is an error, not ignored

    name: str = Field(pattern=r"^[a-z0-9_]+$")
    adapter: Literal["rss", "json_api", "google_news"]
    kind: Literal["funding", "job", "launch"] = "funding"  # funding goes to the digest; others held for now
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
    items: str = ""  # json_api: dotted path to the list of records ("jobs", "data", "hits"); "" = top level
    fields: JsonFields | None = None  # json_api: field mapping
    notes: str = ""

    @model_validator(mode="after")
    def check_adapter_fields(self) -> "Source":
        if self.adapter == "google_news":
            if not self.query:
                raise ValueError("google_news sources need a query")
        elif not self.url:
            raise ValueError(f"{self.adapter} sources need a url")
        if self.adapter == "json_api" and self.enabled and self.fields is None:
            raise ValueError("json_api sources need `fields` (at least title and link or link_template)")
        return self

    def requests(self, language: str = "en") -> list[tuple[str, str, dict | None]]:
        """Every request this source makes: (label, url, params).

        `language` is the Google News interface language (settings.yaml: google_news.language).
        """
        if self.adapter != "google_news":
            return [(self.name, self.url, None)]
        return [
            (
                f"{self.name}[{region}]",
                GOOGLE_NEWS_URL,
                {
                    "q": f"{self.query} when:{self.window}",
                    "hl": f"{language}-{region}",
                    "gl": region,
                    "ceid": f"{region}:{language}",
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


class HttpSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_seconds: float = Field(15, gt=0)
    retries: int = Field(2, ge=0, le=5)  # extra attempts after the first one
    backoff_seconds: list[float] = [2, 5]  # wait before retry 1, retry 2, ...
    max_retry_after_seconds: float = Field(30, ge=0)  # cap on a server's Retry-After
    min_interval_per_host_seconds: float = Field(1.0, ge=0)  # politeness gap per host
    project_url: str = "https://github.com/urmi-labs/anvesh"  # shown in the User-Agent
    contact: str = ""  # email in the User-Agent; RADAR_CONTACT env var is used if empty

    @model_validator(mode="after")
    def enough_backoffs(self) -> "HttpSettings":
        if len(self.backoff_seconds) < self.retries:
            raise ValueError(
                f"backoff_seconds needs at least {self.retries} values (one per retry), "
                f"got {len(self.backoff_seconds)}"
            )
        if any(b < 0 for b in self.backoff_seconds):
            raise ValueError("backoff_seconds values cannot be negative")
        return self


class StateSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_days: int = Field(120, ge=1)  # records not seen for this long are deleted


class GoogleNewsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = Field("en", pattern=r"^[a-z]{2,3}$")  # e.g. en, de, hi


class DigestSettings(BaseModel):
    """How the Telegram digest looks. Placeholders in header: {new} {stories} {fetched} {sources}."""

    model_config = ConfigDict(extra="forbid")

    header: str = "Anvesh: {new} newly funded startups"
    group_by_region: bool = True  # a bold region line (IN, GLOBAL, EU ...) before its stories
    region_order: list[str] = ["IN", "REMOTE", "GLOBAL", "US", "EU", "UK"]  # others follow, A-Z
    show_sources: bool = True  # "inc42 +2" after each headline: where it was reported
    max_stories: int | None = Field(None, ge=1)  # None = all; extra stories wait for the next run
    send_when_empty: bool = False  # send the header even when there is nothing new

    @model_validator(mode="after")
    def header_placeholders_exist(self) -> "DigestSettings":
        try:
            self.header.format(new=0, stories=0, fetched=0, sources=0)
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(
                f"header {self.header!r} has an unknown placeholder {exc}; use {{new}} {{stories}} {{fetched}} {{sources}}"
            ) from exc
        return self


class Settings(BaseModel):
    """settings.yaml: how Anvesh behaves. Every field has a default, so the file is optional."""

    model_config = ConfigDict(extra="forbid")

    http: HttpSettings = Field(default_factory=HttpSettings)
    state: StateSettings = Field(default_factory=StateSettings)
    google_news: GoogleNewsSettings = Field(default_factory=GoogleNewsSettings)
    digest: DigestSettings = Field(default_factory=DigestSettings)


# Default funding patterns. Case-insensitive Python regexes, matched against the title.
DEFAULT_INCLUDE = [
    r"\b(raises?|raised|raising)\b",
    r"\b(secures?|secured|bags?|bagged|lands?|landed|nets?|netted|picks up|snags?)\b.*\b(funding|round|investment|seed|series)\b",
    r"\b(pre-?seed|seed|series [a-f]|pre-series [a-f])\b.*\b(round|funding)\b",
    r"\bfunding round\b",
    r"\b(led by|co-led by)\b",
]
DEFAULT_EXCLUDE = [
    r"\bipos?\b|\bdrhp\b|\blisting\b|\bgoes public\b",
    r"\bacqui(re|res|red|ring|sition|sitions)\b|\bbuys\b|\bmerger\b|\bmerges\b",
    r"\bstake (sale|sells?)\b|\bsells? (a |its )?stake\b|\bblock deals?\b|\bsecondary (sale|transaction)\b",
    r"\blay(s|ing)? off\b|\blayoffs?\b|\bjob cuts?\b|\bshuts? down\b",
    r"\b(closes?|closed|launch(es|ed)?|announces?|unveils?)\b.*\bfund\b",
    r"\bfund (i|ii|iii|iv|v|vi)\b|\bvc fund\b|\bcorpus\b",
    r"\b(govt|government) (seed )?(grant|funding)\b|\bgrants?\b",
    r"\b(this|last) week\b|\bweekly\b|\bround-?ups?\b|\b(funding|deal|weekly) wrap\b|\bfunding galore\b|\bstartups (raised|raise)\b",
]


# Default sector patterns (case-insensitive regex, matched against every headline of a story).
DEFAULT_TECH = [
    r"\bai\b|\bai-(powered|native|first|driven|based)\b|\bartificial intelligence\b|\bmachine learning\b|\bllms?\b|\bgenai\b|\bagents?\b|\bagentic\b",
    r"\bsaas\b|\bsoftware\b|\bplatform\b|\bapps?\b|\bcloud\b|\bdata\b|\banalytics\b|\bapis?\b|\bdevelopers?\b|\bdevops\b|\binfrastructure\b|\bopen[- ]source\b",
    r"\bcyber|\bsecurity\b|\bfintech\b|\bhealthtech\b|\bedtech\b|\binsurtech\b|\bproptech\b|\bagritech\b|\bagtech\b|\bdeeptech\b|\bclimate ?tech\b|\bdefen[cs]e tech\b|\btech\b|\btechnology\b",
    r"\brobot(s|ic|ics)?\b|\bautomat(e|es|ed|ion|ing)\b|\bautonomous\b|\bdrones?\b|\bsatellites?\b|\bspace ?tech\b|\baerospace\b|\bjet engines?\b|\bsemiconductors?\b|\bchips?\b|\bquantum\b",
    r"\bblockchain\b|\bcrypto\b|\bweb3\b|\bdigital\b|\bonline\b|\bmarketplace\b|\bmobility\b|\bev\b|\belectric vehicles?\b|\bbatter(y|ies)\b|\bnuclear\b|\breactor\b|\bbookkeeping\b|\bcompliance\b|\bverification\b|\bsourcing\b",
]
DEFAULT_NON_TECH = [
    r"\bpet (food|care|products?)\b|\bfood\b|\bsnacks?\b|\bbeverages?\b|\bdrinks?\b|\bprotein\b|\bcoffee\b|\btea\b|\bwine\b|\bbeer\b|\bspirits\b|\bliquor\b|\brestaurants?\b|\bcafes?\b|\bbakery\b|\bcloud kitchens?\b",
    r"\bapparel\b|\bfashion\b|\bclothing\b|\bfootwear\b|\bjewel(le)?ry\b|\bhandbags?\b|\bcosmetics?\b|\bskincare\b|\bbeauty\b|\bhaircare\b|\bpersonal care\b|\bperiod products?\b|\bmenstrual\b",
    r"\bfurniture\b|\bhome decor\b|\bd2c\b|\bdtc\b|\bconsumer brands?\b|\breal estate\b|\bhotels?\b|\bhospitality\b",
]


def _check_patterns(kind: str, patterns: list[str]) -> None:
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"{kind} pattern {pattern!r} is not a valid regex: {exc}") from exc


class WindowSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: int = Field(24, ge=1)  # keep signals published this recently (plus the source's lag_hours)
    undated: Literal["keep", "drop"] = "keep"  # keep = treat as published when first seen


class FundingFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_fields: list[Literal["title", "summary"]] = ["title"]
    include: list[str] = Field(default_factory=lambda: list(DEFAULT_INCLUDE))  # any one must match
    exclude: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUDE))  # any one drops it

    @model_validator(mode="after")
    def patterns_compile(self) -> "FundingFilter":
        if not self.match_fields:
            raise ValueError("match_fields needs at least one of: title, summary")
        for kind in ("include", "exclude"):
            _check_patterns(kind, getattr(self, kind))
        return self


class SectorFilter(BaseModel):
    """Keep tech startups only. tech wins over non_tech; a story matching neither is 'unknown'."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    match_fields: list[Literal["title", "summary"]] = ["title", "summary"]
    tech: list[str] = Field(default_factory=lambda: list(DEFAULT_TECH))
    non_tech: list[str] = Field(default_factory=lambda: list(DEFAULT_NON_TECH))
    unknown: Literal["keep", "drop"] = "keep"  # headline says nothing about what the startup does

    @model_validator(mode="after")
    def patterns_compile(self) -> "SectorFilter":
        if not self.match_fields:
            raise ValueError("match_fields needs at least one of: title, summary")
        _check_patterns("tech", self.tech)
        _check_patterns("non_tech", self.non_tech)
        return self


# Words that say nothing about WHICH startup a headline is about. Two headlines only count as
# the same story if they share a word that is not in this list (usually the company name).
DEFAULT_IGNORE_WORDS = """
a an the and or of in on for to with by from at as its it is into via new this that
raises raise raised raising secures secure secured bags bag bagged lands landed nets picks up
snags backs backed funding fund round rounds seed pre-seed pre series follow-on fresh capital
investment investors led co-led startup startups based founder founders co-founder ceo calls
million mn bn billion crore cr lakh rs usd inr eur
ai tech platform company firm develop expand scale help build labs lab health robotics systems
solutions software technologies technology ventures global india indian
""".split()


class DedupeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Same story if this share of their name words overlap (0..1), even with no amount in the title
    title_similarity: float = Field(0.6, gt=0, le=1)
    # Same story if they share one name word AND the same amount in the same currency
    match_on_amount: bool = True
    ignore_words: list[str] = Field(default_factory=lambda: list(DEFAULT_IGNORE_WORDS))


class FiltersConfig(BaseModel):
    """filters.yaml: what counts as a match. Every field has a default, so the file is optional."""

    model_config = ConfigDict(extra="forbid")

    window: WindowSettings = Field(default_factory=WindowSettings)
    funding: FundingFilter = Field(default_factory=FundingFilter)
    dedupe: DedupeSettings = Field(default_factory=DedupeSettings)
    sector: SectorFilter = Field(default_factory=SectorFilter)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"{path} not found")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} is not valid YAML: {exc}") from exc
    if data is None:  # empty file, or only comments
        data = {}
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


def load_settings(config_dir: str | Path) -> Settings:
    """Read settings.yaml if it exists. A missing file means "use every default"."""
    path = Path(config_dir) / "settings.yaml"
    if not path.exists():
        return Settings()
    try:
        return Settings.model_validate(_read_yaml(path))
    except ValidationError as exc:
        raise ConfigError(_format_errors(path.name, exc)) from exc


def load_filters(config_dir: str | Path) -> FiltersConfig:
    """Read filters.yaml if it exists. A missing file means "use every default"."""
    path = Path(config_dir) / "filters.yaml"
    if not path.exists():
        return FiltersConfig()
    try:
        return FiltersConfig.model_validate(_read_yaml(path))
    except ValidationError as exc:
        raise ConfigError(_format_errors(path.name, exc)) from exc
