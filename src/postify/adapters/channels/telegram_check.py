from __future__ import annotations

import httpx


class TelegramChannelChecker:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def check(self, configuration: dict[str, object], secret: str) -> str:
        try:
            response = self._client.get(
                f"https://api.telegram.org/bot{secret}/getMe", timeout=10.0
            )
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            return "unavailable"
        return "ok" if isinstance(payload, dict) and payload.get("ok") is True else "failed"
