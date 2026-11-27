import httpx
import pytest

from anvesh.telegram import MAX_LEN, Telegram, TelegramError, split_text


def test_short_text_is_one_chunk():
    assert split_text("hello") == ["hello"]


def test_empty_text_gives_no_chunks():
    assert split_text("") == []


def test_long_text_splits_at_line_breaks():
    line = "x" * 100
    text = "\n".join([line] * 100)  # about 10,100 characters
    chunks = split_text(text)
    assert len(chunks) == 3
    assert all(len(c) <= MAX_LEN for c in chunks)
    assert all(c.startswith("x") and c.endswith("x") for c in chunks)


def test_text_without_line_breaks_is_hard_cut():
    chunks = split_text("y" * 9000)
    assert [len(c) for c in chunks] == [4096, 4096, 808]


def test_missing_env_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(TelegramError, match="TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"):
        Telegram.from_env()


def test_rejected_message_raises():
    def handler(request):
        return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(TelegramError, match="chat not found"):
        Telegram("token", "123", client=client).send("hi")


def test_sent_message_has_chat_and_text():
    seen = []

    def handler(request):
        seen.append(request.content.decode())
        return httpx.Response(200, json={"ok": True, "result": {}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    Telegram("token", "123", client=client).send("hello")
    assert "chat_id=123" in seen[0] and "text=hello" in seen[0]
