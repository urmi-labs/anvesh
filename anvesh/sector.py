"""Sector filter: keep tech startups, drop raises that are clearly not tech.

A story is classified from ALL its merged headlines (and their feed summaries), because one outlet
writes "Lampsy Health Raises €1.1M" and another "... AI bedside lamp ...".
  tech      a tech pattern matched (wins even if a non-tech one matched too: "AI food app" is tech)
  non_tech  only a non-tech pattern matched  -> dropped
  unknown   nothing matched ("Sooner Raises $20M")  -> sector.unknown decides, keep by default
"""

import re
from dataclasses import dataclass, field

from anvesh.config import SectorFilter
from anvesh.dedupe import Story

TECH = "tech"
NON_TECH = "non_tech"
UNKNOWN = "unknown"


class SectorClassifier:
    """Compiles the patterns once, then classifies many stories."""

    def __init__(self, settings: SectorFilter):
        self.settings = settings
        self.tech = [re.compile(p, re.IGNORECASE) for p in settings.tech]
        self.non_tech = [re.compile(p, re.IGNORECASE) for p in settings.non_tech]

    def text(self, story: Story) -> str:
        signals = story.signals or [story.signal]
        return " \n ".join(getattr(s, f) for s in signals for f in self.settings.match_fields)

    def classify(self, story: Story) -> str:
        text = self.text(story)
        if any(p.search(text) for p in self.tech):
            return TECH
        if any(p.search(text) for p in self.non_tech):
            return NON_TECH
        return UNKNOWN


@dataclass
class SectorResult:
    kept: list[Story] = field(default_factory=list)
    dropped: list[Story] = field(default_factory=list)  # shown in dry-run, so mistakes are visible
    unknown: int = 0  # kept or dropped, how many said nothing about their sector


def filter_sector(stories: list[Story], settings: SectorFilter) -> SectorResult:
    result = SectorResult()
    if not settings.enabled:
        result.kept = list(stories)
        return result
    classifier = SectorClassifier(settings)
    for story in stories:
        label = classifier.classify(story)
        if label == UNKNOWN:
            result.unknown += 1
        if label == NON_TECH or (label == UNKNOWN and settings.unknown == "drop"):
            result.dropped.append(story)
        else:
            result.kept.append(story)
    return result
