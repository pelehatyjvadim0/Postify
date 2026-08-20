from __future__ import annotations

import httpx

from postify.adapters.channels.telegram_check import TelegramChannelChecker


def test_check_fails_when_bot_cannot_access_configured_chat() -> None:
    # Break caught: a valid bot token is reported ok while the configured target is inaccessible.
    requested: list[str] = []

    def telegram(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"id": 1}})
        return httpx.Response(200, json={"ok": False, "error_code": 400})

    with httpx.Client(transport=httpx.MockTransport(telegram)) as client:
        checker = TelegramChannelChecker(client)
        result = checker.check({"chat_id": "-10077"}, "bot-token")

    assert result == "failed"
    assert checker.last_reason == "Канал не найден. Проверьте @username и добавьте бота в канал."
    assert requested == [
        "https://api.telegram.org/botbot-token/getMe",
        "https://api.telegram.org/botbot-token/getChat?chat_id=-10077",
    ]


def test_check_passes_only_for_channel_admin_allowed_to_publish() -> None:
    requested: list[str] = []

    def telegram(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"id": 42}})
        if request.url.path.endswith("/getChat"):
            return httpx.Response(200, json={"ok": True, "result": {"id": -10077}})
        return httpx.Response(200, json={
            "ok": True,
            "result": {"status": "administrator", "can_post_messages": True},
        })

    with httpx.Client(transport=httpx.MockTransport(telegram)) as client:
        result = TelegramChannelChecker(client).check(
            {"chat_id": "@aioiai_ai_news"}, "bot-token"
        )

    assert result == "ok"
    assert requested == [
        "https://api.telegram.org/botbot-token/getMe",
        "https://api.telegram.org/botbot-token/getChat?chat_id=%40aioiai_ai_news",
        "https://api.telegram.org/botbot-token/getChatMember?chat_id=%40aioiai_ai_news&user_id=42",
    ]


def test_check_fails_when_channel_admin_cannot_publish() -> None:
    def telegram(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"id": 42}})
        if request.url.path.endswith("/getChat"):
            return httpx.Response(200, json={"ok": True, "result": {"id": -10077}})
        return httpx.Response(200, json={
            "ok": True,
            "result": {"status": "administrator", "can_post_messages": False},
        })

    with httpx.Client(transport=httpx.MockTransport(telegram)) as client:
        checker = TelegramChannelChecker(client)
        result = checker.check({"chat_id": "-10077"}, "bot-token")

    assert result == "failed"
    assert checker.last_reason == "Разрешите боту публиковать сообщения в настройках администраторов канала."
