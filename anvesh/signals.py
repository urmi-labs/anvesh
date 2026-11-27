"""Signal: one item found by a source (a news story, a launch post, a job post)."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Signal:
    source: str  # source name from sources.yaml, e.g. "inc42"
    title: str  # headline, cleaned of HTML and extra spaces
    link: str  # URL of the story
    publisher: str  # who published it, e.g. "Inc42 Media"
    published: str | None  # UTC ISO time (state.to_iso), None if the feed gave no date
    region: str  # what the source covers (IN, US, EU, GLOBAL, REMOTE ...)
    summary: str = ""  # plain-text description from the feed, may be empty

    def to_dict(self) -> dict:
        return asdict(self)
