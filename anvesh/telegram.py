"""Send messages to a Telegram chat through the Bot API."""

import json
import os
import time

import httpx

API_BASE = "https://api.telegram.org"
MAX_LEN = 4096  # Telegram's limit for one message
SEND_GAP_SECONDS = 1.1  # Telegram advises about one message a second per chat


class TelegramError(RuntimeError):
    """Raised when Telegram is not configured or rejects a message."""


def split_text(text: str, limit: int = MAX_LEN) -> list[str]:
    """Split text into chunks of at most `limit` characters, cutting at line breaks when possible."""
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


class Telegram:
    def __init__(self, token: str, chat_id: str, client: httpx.Client | None = None):
        self.token = token
        self.chat_id = chat_id
        self.client = client or httpx.Client(timeout=15)
        self._last_sent = 0.0

    @classmethod
    def from_env(cls) -> "Telegram":
        """Build a sender from TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        missing = [name for name, value in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat_id)) if not value]
        if missing:
            raise TelegramError(f"missing environment variables: {', '.join(missing)}")
        return cls(token, chat_id)

    def send(self, text: str, parse_mode: str | None = None, split: bool = True) -> None:
        """Send text, split into several messages if it is too long.

        parse_mode="HTML" lets the text use <a href>, <b>; the caller must escape everything else.
        split=False sends text as one message: use it for HTML the caller already packed to size,
        because split_text counts raw characters and could cut through a tag.
        """
        for chunk in split_text(text) if split else [text]:
            wait = SEND_GAP_SECONDS - (time.monotonic() - self._last_sent)
            if wait > 0:
                time.sleep(wait)
            data = {
                "chat_id": self.chat_id,
                "text": chunk,
                "link_preview_options": json.dumps({"is_disabled": True}),
            }
            if parse_mode:
                data["parse_mode"] = parse_mode
            response = self.client.post(f"{API_BASE}/bot{self.token}/sendMessage", data=data)
            self._last_sent = time.monotonic()
            try:
                body = response.json()
            except ValueError:
                body = {}
            if response.status_code != 200 or not body.get("ok"):
                description = body.get("description", "no description")
                raise TelegramError(f"sendMessage failed: HTTP {response.status_code}, {description}")
