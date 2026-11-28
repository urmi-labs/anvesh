"""Dedupe: many headlines about one raise become one Story.

Two layers, both inside one run:
1. Same link: Google News returns the identical article once per region.
2. Same story: different outlets, different wording. Two headlines are the same story when
   - most of their "name words" overlap (title_similarity), or
   - they share at least one name word AND state the same amount in the same currency.
   "Name words" are the title's words minus ignore_words (raises, startup, seed, ...),
   so what is left is mostly the company name, place and product.
Currencies are never converted: a wrong merge hides a startup, a missed merge only repeats it.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from anvesh.config import DedupeSettings
from anvesh.signals import Signal

CURRENCY = {"$": "usd", "usd": "usd", "€": "eur", "eur": "eur", "₹": "inr", "rs": "inr", "inr": "inr",
            "£": "gbp", "gbp": "gbp", "a$": "aud", "s$": "sgd"}
SCALE = {"k": 1e3, "lakh": 1e5, "m": 1e6, "mn": 1e6, "million": 1e6, "cr": 1e7, "crore": 1e7,
         "b": 1e9, "bn": 1e9, "billion": 1e9, "": 1}
AMOUNT = re.compile(
    r"(a\$|s\$|\$|€|₹|£|\busd\b|\beur\b|\bgbp\b|\binr\b|\brs\b\.?)\s?(\d[\d,]*(?:\.\d+)?)\s?"
    r"(million|mn|m|billion|bn|b|lakh|crore|cr|k)?\b",
    re.IGNORECASE,
)
WORD = re.compile(r"[a-z0-9][a-z0-9-]*")
TRACKING = ("utm_", "fbclid", "gclid", "ref")


def normalise_link(link: str) -> str:
    """Same article, same key: lowercase host, no tracking params, no #fragment, no trailing /."""
    parts = urlsplit(link.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(TRACKING)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def amounts(title: str) -> frozenset[tuple[str, int]]:
    """Every money amount in a title as (currency, whole units): '$9 Mn' -> ('usd', 9000000)."""
    found = set()
    for symbol, number, unit in AMOUNT.findall(title):
        value = float(number.replace(",", "")) * SCALE[unit.lower()]
        found.add((CURRENCY[symbol.lower().rstrip(".")], int(round(value, -3))))
    return frozenset(found)


def name_words(title: str, ignore: frozenset[str]) -> frozenset[str]:
    """Title words that could identify the startup. Amounts and possessive 's are removed first."""
    text = AMOUNT.sub(" ", title.lower().replace("’", "'").replace("‘", "'"))
    text = re.sub(r"'s?\b", " ", text)
    words = set()
    for word in WORD.findall(text):
        word = word.strip("-")
        if not word or word in ignore:
            continue
        if word.isdigit() and len(word) < 3:  # "2", "50" say nothing; "009" may be a name
            continue
        words.add(word)
    return frozenset(words)


@dataclass(frozen=True)
class Fingerprint:
    """What dedupe compares for one headline."""

    words: frozenset[str]
    amounts: frozenset[tuple[str, int]]


def fingerprint(title: str, ignore: frozenset[str]) -> Fingerprint:
    return Fingerprint(name_words(title, ignore), amounts(title))


def same_story(a: Fingerprint, b: Fingerprint, settings: DedupeSettings) -> bool:
    shared = a.words & b.words
    if not shared:
        return False
    if len(shared) / len(a.words | b.words) >= settings.title_similarity:
        return True
    return settings.match_on_amount and bool(a.amounts & b.amounts)


@dataclass
class Story:
    """One raise. `signal` is the best headline; `sources` lists everywhere it appeared."""

    signal: Signal
    sources: list[str] = field(default_factory=list)
    prints: list[Fingerprint] = field(default_factory=list)  # one per merged headline

    def also_in(self) -> list[str]:
        """Sources other than the one whose headline and link are shown."""
        return [name for name in self.sources if name != self.signal.source]

    def matches(self, other: Fingerprint, settings: DedupeSettings) -> bool:
        return any(same_story(p, other, settings) for p in self.prints)


def _better(current: Signal, candidate: Signal) -> bool:
    """Prefer a direct publisher link over a news.google.com redirect."""
    return "news.google.com" in current.link and "news.google.com" not in candidate.link


def dedupe(signals: list[Signal], settings: DedupeSettings) -> list[Story]:
    ignore = frozenset(w.lower() for w in settings.ignore_words)
    seen_links: set[str] = set()
    stories: list[Story] = []
    for signal in signals:
        link = normalise_link(signal.link)
        if link in seen_links:
            continue  # layer 1: exact same article
        seen_links.add(link)
        print_ = fingerprint(signal.title, ignore)
        for story in stories:  # layer 2: same raise, other outlet
            if story.matches(print_, settings):
                story.prints.append(print_)
                if signal.source not in story.sources:
                    story.sources.append(signal.source)
                if _better(story.signal, signal):
                    story.signal = signal
                break
        else:
            stories.append(Story(signal, [signal.source], [print_]))
    return stories


def story_record(story: Story) -> dict:
    """What the seen_stories table keeps about a delivered story (JSON-safe)."""
    return {
        "title": story.signal.title,
        "link": story.signal.link,
        "sources": list(story.sources),
        "prints": [
            {"words": sorted(p.words), "amounts": sorted([c, v] for c, v in p.amounts)} for p in story.prints
        ],
    }


def story_key(story: Story) -> str:
    return normalise_link(story.signal.link)


class SeenStories:
    """Stories delivered in earlier runs, read from the `seen_stories` state table.

    A new story counts as seen when it matches a remembered one the same way dedupe merges
    two headlines, so tomorrow's re-publication by another outlet is not sent again.
    Records are refreshed when matched, so a story keeps being recognised while it is in the news.
    """

    def __init__(self, table, settings: DedupeSettings):
        self.table = table
        self.settings = settings
        self._prints: list[tuple[str, Fingerprint]] = []
        for key, record in table.records.items():
            for p in record.get("prints", []):
                amounts_ = frozenset((c, int(v)) for c, v in p.get("amounts", []))
                self._prints.append((key, Fingerprint(frozenset(p.get("words", [])), amounts_)))

    def match(self, story: Story) -> str | None:
        """Key of the remembered story this one repeats, or None if it is new."""
        if story_key(story) in self.table:
            return story_key(story)
        for key, old in self._prints:
            if story.matches(old, self.settings):
                return key
        return None

    def remember(self, story: Story, now=None) -> None:
        """Call only after the story was really delivered."""
        key = self.match(story) or story_key(story)
        self.table.upsert(key, story_record(story) if key not in self.table else {}, now=now)
        if key == story_key(story):
            for p in story.prints:
                self._prints.append((key, p))
