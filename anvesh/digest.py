"""Turn the run's new stories into Telegram messages (HTML mode).

Each story is one line: the headline is the link, so long news.google.com URLs never show as text.
Messages are packed to at most Telegram's 4096 characters, and each Message knows which stories it
carries, so the caller can remember exactly the stories that were delivered.
"""

import html
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from anvesh.config import DigestSettings
from anvesh.dedupe import Story
from anvesh.telegram import MAX_LEN, TelegramError


@dataclass
class Message:
    text: str
    stories: list[Story] = field(default_factory=list)


def story_line(story: Story, settings: DigestSettings) -> str:
    """'• <a href="link">Headline</a> · inc42 +2'"""
    link = html.escape(story.signal.link, quote=True)
    line = f'• <a href="{link}">{html.escape(story.signal.title)}</a>'
    if settings.show_sources:
        others = len(story.also_in())
        line += f" · {html.escape(story.signal.source)}" + (f" +{others}" if others else "")
    return line


def _region_rank(region: str, order: list[str]) -> tuple[int, str]:
    return (order.index(region), "") if region in order else (len(order), region)


def build_messages(stories: list[Story], counts: dict, settings: DigestSettings,
                   limit: int = MAX_LEN) -> tuple[list[Message], int]:
    """Messages to send, and how many stories were held back by max_stories."""
    shown = stories[: settings.max_stories] if settings.max_stories else list(stories)
    held_back = len(stories) - len(shown)
    if not shown and not settings.send_when_empty:
        return [], held_back

    header = "<b>" + html.escape(settings.header.format(**counts)) + "</b>"
    if held_back:
        header += f"\n{held_back} more next run"
    if settings.group_by_region:
        # stable sort: inside one region, stories keep the order the sources gave them
        shown.sort(key=lambda s: _region_rank(s.signal.region, settings.region_order))

    messages = [Message(header)]
    region = None
    for story in shown:
        line = story_line(story, settings)
        heading = f"<b>{html.escape(story.signal.region)}</b>" if settings.group_by_region else ""
        new_region = settings.group_by_region and story.signal.region != region
        region = story.signal.region
        block = f"\n{heading}\n{line}" if new_region else line
        current = messages[-1]
        if len(current.text) + 1 + len(block) > limit:
            # start a new message; repeat the region heading so the stories keep their context
            current = Message(f"{heading}\n{line}" if heading else line)
            messages.append(current)
        else:
            current.text += "\n" + block
        current.stories.append(story)
    return messages, held_back


def deliver(
    messages: list[Message], send: Callable[[str], None], remember: Callable[[Story], None]
) -> tuple[int, Exception | None]:
    """Send messages in order. After each one goes out, remember its stories.

    Stops at the first failure and returns (stories delivered, the error). Stories of the failed
    and later messages are not remembered, so the next run sends them again: none lost, none twice.
    """
    delivered = 0
    for message in messages:
        try:
            send(message.text)
        except (TelegramError, httpx.HTTPError) as exc:
            return delivered, exc
        for story in message.stories:
            remember(story)
        delivered += len(message.stories)
    return delivered, None
