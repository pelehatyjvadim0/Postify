from __future__ import annotations

import httpx


class TelegramChannelChecker:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def check(self, configuration: dict[str, object], secret: str) -> str:
        try:
            identity = self._client.get(
                f"https://api.telegram.org/bot{secret}/getMe", timeout=10.0
            )
            identity_payload = identity.json()
            chat_id = configuration.get("chat_id")
            if not isinstance(chat_id, str) or not chat_id.strip():
                return "failed"
            target = self._client.get(
                f"https://api.telegram.org/bot{secret}/getChat",
                params={"chat_id": chat_id},
                timeout=10.0,
            )
            target_payload = target.json()
        except (httpx.HTTPError, ValueError, TypeError):
            return "unavailable"
        if not isinstance(identity_payload, dict) or identity_payload.get("ok") is not True:
            return "failed"
        return "ok" if isinstance(target_payload, dict) and target_payload.get("ok") is True else "failed"
