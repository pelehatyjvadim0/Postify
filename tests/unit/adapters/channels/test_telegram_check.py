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
        result = TelegramChannelChecker(client).check({"chat_id": "-10077"}, "bot-token")

    assert result == "failed"
    assert requested == [
        "https://api.telegram.org/botbot-token/getMe",
        "https://api.telegram.org/botbot-token/getChat?chat_id=-10077",
    ]
