"""Бот входа: разбор апдейтов, ответы в Telegram и устойчивость цикла.

Telegram подменён транспортом httpx — сеть не трогается.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from functools import wraps
import json
import hashlib
import hmac
from pathlib import Path
import sys
from typing import Any

import httpx
import pytest

from postify.adapters.telegram.auth_bot import (
    APPROVED_TEXT,
    CONFIRM_TEXT,
    DENIED_TEXT,
    EXPIRED_TEXT,
    FOREIGN_TEXT,
    NO_BUTTON,
    STALE_TEXT,
    YES_BUTTON,
    AuthBotPoller,
    TelegramAuthBot,
    TelegramAuthError,
)
from postify.application.auth.service import AuthService

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "application" / "auth"))
from fakes import FakeUserRepository  # noqa: E402


def asyncio_test(test):
    """Запускает корутину теста: pytest-asyncio в зависимостях проекта нет."""

    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))

    return run


TOKEN = "777:SENTINEL-AUTH-TOKEN"
NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


class FakeTelegram:
    """Подставной Bot API: копит вызовы и отдаёт заготовленные апдейты."""

    def __init__(self, *, username: str = "autopost_auth_bot") -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.updates: list[dict[str, Any]] = []
        self.username = username
        self.failures = 0

    async def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content or b"{}")
        self.calls.append((method, body))
        if self.failures:
            self.failures -= 1
            return httpx.Response(500, json={"ok": False, "description": "сбой"})
        if method == "getMe":
            return httpx.Response(
                200, json={"ok": True, "result": {"id": 777, "username": self.username}}
            )
        if method == "getUpdates":
            updates, self.updates = self.updates, []
            if not updates:
                # Пустой long polling в Telegram висит до таймаута; здесь
                # короткая пауза, иначе цикл крутится без уступки другим задачам.
                await asyncio.sleep(0.005)
            return httpx.Response(200, json={"ok": True, "result": updates})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 90}})

    def method_calls(self, method: str) -> list[dict[str, Any]]:
        return [body for name, body in self.calls if name == method]


def build(*, username: str | None = None, telegram: FakeTelegram | None = None):
    telegram = telegram or FakeTelegram()
    client = httpx.AsyncClient(transport=httpx.MockTransport(telegram.handler))
    repository = FakeUserRepository()
    service = AuthService(repository, bot_username=username, clock=lambda: NOW)
    bot = TelegramAuthBot(client, bot_token=TOKEN)
    return telegram, client, service, AuthBotPoller(
        bot, service, poll_timeout=0, retry_delay=0.01
    )


def start_update(token: str, user_id: int) -> dict[str, Any]:
    return {
        "update_id": user_id,
        "message": {
            "message_id": 1,
            "text": f"/start autopost_login_{token}",
            "chat": {"id": user_id},
            "from": {
                "id": user_id,
                "first_name": "Иван",
                "last_name": "Петров",
                "username": f"user_{user_id}",
            },
        },
    }


def decision_update(token: str, user_id: int, decision: str) -> dict[str, Any]:
    return {
        "update_id": user_id + 1000,
        "callback_query": {
            "id": f"callback-{user_id}",
            "data": f"autopost_login_{decision}_{token}",
            "from": {"id": user_id},
            "message": {"message_id": 90, "chat": {"id": user_id}},
        },
    }


@asyncio_test
async def test_start_moves_request_to_confirmation_and_shows_both_buttons() -> None:
    telegram, client, service, poller = build(username="autopost_auth_bot")
    request, _ = service.start_login(ip="10.0.0.1")
    try:
        await poller.handle(start_update(request.telegram_token, 101))
    finally:
        await client.aclose()

    sent = telegram.method_calls("sendMessage")[0]
    keyboard = sent["reply_markup"]["inline_keyboard"]
    assert sent["text"] == CONFIRM_TEXT
    assert keyboard[0][0] == {
        "text": YES_BUTTON,
        "callback_data": f"autopost_login_yes_{request.telegram_token}",
    }
    assert keyboard[1][0] == {
        "text": NO_BUTTON,
        "callback_data": f"autopost_login_no_{request.telegram_token}",
    }
    assert service.complete_login.status(request.browser_token) == "confirmation"


@asyncio_test
async def test_approval_edits_the_message_and_opens_the_session() -> None:
    telegram, client, service, poller = build(username="autopost_auth_bot")
    request, _ = service.start_login(ip="10.0.0.1")
    try:
        await poller.handle(start_update(request.telegram_token, 101))
        await poller.handle(decision_update(request.telegram_token, 101, "yes"))
    finally:
        await client.aclose()

    assert telegram.method_calls("editMessageText")[0]["text"] == APPROVED_TEXT
    # Пустой answerCallbackQuery: кнопка принята без всплывающего текста.
    assert telegram.method_calls("answerCallbackQuery")[-1] == {
        "callback_query_id": "callback-101"
    }
    assert service.complete_login(request.browser_token).user.telegram_user_id == "101"


@asyncio_test
async def test_denial_edits_the_message_and_keeps_status_denied() -> None:
    telegram, client, service, poller = build(username="autopost_auth_bot")
    request, _ = service.start_login(ip="10.0.0.1")
    try:
        await poller.handle(start_update(request.telegram_token, 303))
        await poller.handle(decision_update(request.telegram_token, 303, "no"))
    finally:
        await client.aclose()

    assert telegram.method_calls("editMessageText")[0]["text"] == DENIED_TEXT
    assert service.complete_login.status(request.browser_token) == "denied"


@asyncio_test
async def test_foreign_press_is_rejected_with_an_alert() -> None:
    # Поломка: чужое нажатие без сверки id открывает сессию перехватчику.
    telegram, client, service, poller = build(username="autopost_auth_bot")
    request, _ = service.start_login(ip="10.0.0.1")
    try:
        await poller.handle(start_update(request.telegram_token, 101))
        await poller.handle(decision_update(request.telegram_token, 202, "yes"))
    finally:
        await client.aclose()

    assert telegram.method_calls("answerCallbackQuery")[-1] == {
        "callback_query_id": "callback-202",
        "text": FOREIGN_TEXT,
        "show_alert": True,
    }
    assert not telegram.method_calls("editMessageText")
    assert service.complete_login.status(request.browser_token) == "confirmation"


@asyncio_test
async def test_start_with_unknown_token_answers_that_it_expired() -> None:
    telegram, client, service, poller = build(username="autopost_auth_bot")
    try:
        await poller.handle(start_update("x" * 43, 101))
    finally:
        await client.aclose()

    sent = telegram.method_calls("sendMessage")[0]
    assert sent["text"] == EXPIRED_TEXT
    assert "reply_markup" not in sent


@asyncio_test
async def test_press_on_a_request_without_confirmation_is_stale() -> None:
    telegram, client, service, poller = build(username="autopost_auth_bot")
    request, _ = service.start_login(ip="10.0.0.1")
    try:
        await poller.handle(decision_update(request.telegram_token, 101, "yes"))
    finally:
        await client.aclose()

    assert telegram.method_calls("answerCallbackQuery")[-1] == {
        "callback_query_id": "callback-101",
        "text": STALE_TEXT,
        "show_alert": True,
    }


@asyncio_test
async def test_unrelated_updates_do_not_touch_telegram() -> None:
    telegram, client, service, poller = build(username="autopost_auth_bot")
    try:
        await poller.handle({"update_id": 1, "message": {"text": "привет"}})
        await poller.handle({"update_id": 2, "edited_message": {"text": "/start"}})
        await poller.handle(
            {"update_id": 3, "callback_query": {"id": "c", "data": "мусор"}}
        )
    finally:
        await client.aclose()

    assert telegram.calls == []


@asyncio_test
async def test_username_comes_from_getme_when_setting_is_empty() -> None:
    telegram, client, service, poller = build(username=None)
    try:
        assert await poller.resolve_username() == "autopost_auth_bot"
        # Повторный запрос имени в Telegram не ходит.
        assert await poller.resolve_username() == "autopost_auth_bot"
    finally:
        await client.aclose()

    assert len(telegram.method_calls("getMe")) == 1


@asyncio_test
async def test_configured_username_skips_getme() -> None:
    telegram, client, service, poller = build(username="@autopost_auth_bot")
    try:
        assert await poller.resolve_username() == "autopost_auth_bot"
    finally:
        await client.aclose()

    assert telegram.calls == []


@asyncio_test
async def test_telegram_failure_is_reported_and_not_swallowed() -> None:
    telegram, client, service, poller = build(username="autopost_auth_bot")
    telegram.failures = 1
    try:
        with pytest.raises(TelegramAuthError):
            await poller._bot.get_updates(offset=0, timeout=0)
    finally:
        await client.aclose()


@asyncio_test
async def test_polling_loop_survives_telegram_errors_and_processes_updates() -> None:
    # Риск Р10: сбой Telegram не должен убивать единственный цикл входа.
    telegram = FakeTelegram()
    telegram.failures = 2
    _, client, service, poller = build(username="autopost_auth_bot", telegram=telegram)
    request, _ = service.start_login(ip="10.0.0.1")
    telegram.updates = [start_update(request.telegram_token, 101)]

    task = asyncio.create_task(poller.run())
    try:
        for _ in range(200):
            await asyncio.sleep(0.01)
            if service.complete_login.status(request.browser_token) == "confirmation":
                break
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await client.aclose()

    assert service.complete_login.status(request.browser_token) == "confirmation"


@asyncio_test
async def test_offset_advances_so_updates_are_not_replayed() -> None:
    telegram = FakeTelegram()
    _, client, service, poller = build(username="autopost_auth_bot", telegram=telegram)
    request, _ = service.start_login(ip="10.0.0.1")
    telegram.updates = [start_update(request.telegram_token, 101)]

    task = asyncio.create_task(poller.run())
    try:
        for _ in range(200):
            await asyncio.sleep(0.01)
            if len(telegram.method_calls("getUpdates")) >= 2:
                break
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await client.aclose()

    offsets = [call["offset"] for call in telegram.method_calls("getUpdates")]
    assert offsets[0] == 0
    assert offsets[-1] == 102
    assert telegram.method_calls("getUpdates")[0]["allowed_updates"] == [
        "message",
        "callback_query",
    ]


@asyncio_test
async def test_bot_token_never_leaks_into_request_payloads() -> None:
    telegram, client, service, poller = build(username="autopost_auth_bot")
    request, _ = service.start_login(ip="10.0.0.1")
    try:
        await poller.handle(start_update(request.telegram_token, 101))
    finally:
        await client.aclose()

    assert TOKEN not in json.dumps(telegram.calls, ensure_ascii=False)


@asyncio_test
async def test_shared_bot_reads_only_the_relay_and_sends_answers_to_telegram() -> None:
    seen = []
    update = start_update("x" * 43, 101)

    async def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": [update]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        bot = TelegramAuthBot(client, bot_token=TOKEN, relay_url="http://127.0.0.1:18080/_auth/autoposttg/updates")
        assert await bot.get_updates(offset=42) == [update]
        await bot.send_message(chat_id=101, text=CONFIRM_TEXT)
    assert seen[0].url.host == "127.0.0.1"
    assert json.loads(seen[0].content) == {"offset": 42}
    expected = hmac.new(TOKEN.encode(), b"autoposttg-auth-relay-v1", hashlib.sha256).hexdigest()
    assert seen[0].headers["authorization"] == f"Bearer {expected}"
    assert TOKEN not in str(seen[0].url) + str(seen[0].headers)
    assert seen[1].url.host == "api.telegram.org"
    assert "authorization" not in seen[1].headers
    assert all(not request.url.path.endswith("getUpdates") for request in seen)


@asyncio_test
async def test_relay_failure_never_falls_back_to_telegram_polling() -> None:
    seen = []

    async def handler(request):
        seen.append(request)
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        bot = TelegramAuthBot(client, bot_token=TOKEN, relay_url="https://relay.example/updates")
        with pytest.raises(TelegramAuthError, match="общего бота"):
            await bot.get_updates(offset=0)
    assert len(seen) == 1
    assert seen[0].url.host == "relay.example"


@pytest.mark.parametrize("url", ["http://example.com/updates", "https://user:pass@example.com/updates", "file:///tmp/relay"])
@asyncio_test
async def test_relay_rejects_unsafe_addresses(url) -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="HTTPS"):
            TelegramAuthBot(client, bot_token=TOKEN, relay_url=url)


@asyncio_test
async def test_storychat_updates_cannot_confirm_an_autopost_login() -> None:
    telegram, client, service, poller = build(username="autopost_auth_bot")
    request, url = service.start_login(ip="10.0.0.1")
    try:
        update = start_update(request.telegram_token, 101)
        update["message"]["text"] = f"/start login_{request.telegram_token}"
        await poller.handle(update)
        callback = decision_update(request.telegram_token, 101, "yes")
        callback["callback_query"]["data"] = f"login_yes_{request.telegram_token}"
        await poller.handle(callback)
    finally:
        await client.aclose()
    assert service.complete_login.status(request.browser_token) == "pending"
    assert not telegram.calls
    assert len(url.split("start=")[1]) <= 64
    assert len(f"autopost_login_yes_{request.telegram_token}".encode()) <= 64


@asyncio_test
async def test_failed_confirmation_delivery_can_be_retried_without_losing_login() -> None:
    telegram, client, service, poller = build(username="autopost_auth_bot")
    request, _ = service.start_login(ip="10.0.0.1")
    telegram.failures = 1
    try:
        with pytest.raises(TelegramAuthError):
            await poller.handle(start_update(request.telegram_token, 101))
        await poller.handle(start_update(request.telegram_token, 101))
        assert telegram.method_calls("sendMessage")[-1]["text"] == CONFIRM_TEXT
        telegram.failures = 1
        with pytest.raises(TelegramAuthError):
            await poller.handle(decision_update(request.telegram_token, 101, "yes"))
        await poller.handle(decision_update(request.telegram_token, 101, "yes"))
        assert telegram.method_calls("editMessageText")[-1]["text"] == APPROVED_TEXT
        assert service.complete_login(request.browser_token).user.telegram_user_id == "101"
    finally:
        await client.aclose()


@asyncio_test
async def test_failed_update_is_not_acknowledged_before_retry() -> None:
    telegram, client, service, poller = build(username="autopost_auth_bot")
    request, _ = service.start_login(ip="10.0.0.1")
    update = start_update(request.telegram_token, 101)
    offsets = []
    attempts = 0

    async def updates(*, offset, timeout):
        offsets.append(offset)
        if len(offsets) == 3:
            raise asyncio.CancelledError()
        return [update]

    original = poller.handle

    async def handle(item):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TelegramAuthError("temporary failure")
        await original(item)

    poller._bot.get_updates = updates
    poller.handle = handle
    try:
        with pytest.raises(asyncio.CancelledError):
            await poller.run()
    finally:
        await client.aclose()
    assert offsets == [0, 0, 102]


@asyncio_test
async def test_blocked_user_does_not_block_other_logins() -> None:
    telegram, client, service, poller = build(username="autopost_auth_bot")
    first, _ = service.start_login(ip="10.0.0.1")
    second, _ = service.start_login(ip="10.0.0.2")
    offsets = []
    original = poller.handle

    async def updates(*, offset, timeout):
        offsets.append(offset)
        if len(offsets) == 2:
            raise asyncio.CancelledError()
        return [start_update(first.telegram_token, 101), start_update(second.telegram_token, 102)]

    async def handle(update):
        if update["update_id"] == 101:
            raise TelegramAuthError("sendMessage: bot blocked", retryable=False)
        await original(update)

    poller._bot.get_updates = updates
    poller.handle = handle
    try:
        with pytest.raises(asyncio.CancelledError):
            await poller.run()
    finally:
        await client.aclose()
    assert offsets == [0, 103]
    assert service.complete_login.status(second.browser_token) == "confirmation"


@pytest.mark.parametrize("method, description", [
    ("answerCallbackQuery", "Bad Request: query is too old and response timeout expired or query ID is invalid"),
    ("editMessageText", "Bad Request: message is not modified"),
])
@asyncio_test
async def test_replayed_telegram_response_does_not_stall_the_queue(method, description) -> None:
    async def handler(request):
        return httpx.Response(400, json={"ok": False, "error_code": 400, "description": description})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        bot = TelegramAuthBot(client, bot_token=TOKEN)
        assert await bot._call(method, {}, timeout=1) is None
