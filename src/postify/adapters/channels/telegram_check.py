from __future__ import annotations

import httpx


class TelegramChannelChecker:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client
        self.last_reason = ""

    def _finish(self, status: str, reason: str = "") -> str:
        self.last_reason = reason
        return status

    def check(self, configuration: dict[str, object], secret: str) -> str:
        try:
            identity = self._client.get(
                f"https://api.telegram.org/bot{secret}/getMe", timeout=10.0
            )
            identity_payload = identity.json()
            if not isinstance(identity_payload, dict) or identity_payload.get("ok") is not True:
                return self._finish(
                    "failed",
                    "Токен бота недействителен. Получите новый токен у @BotFather.",
                )
            identity_result = identity_payload.get("result")
            if not isinstance(identity_result, dict) or not isinstance(identity_result.get("id"), int):
                return self._finish("failed", "Telegram не вернул идентификатор бота. Проверьте токен.")
            chat_id = configuration.get("chat_id")
            if not isinstance(chat_id, str) or not chat_id.strip():
                return self._finish("failed", "Укажите @username Telegram-канала.")
            target = self._client.get(
                f"https://api.telegram.org/bot{secret}/getChat",
                params={"chat_id": chat_id},
                timeout=10.0,
            )
            target_payload = target.json()
            if not isinstance(target_payload, dict) or target_payload.get("ok") is not True:
                return self._finish(
                    "failed",
                    "Канал не найден. Проверьте @username и добавьте бота в канал.",
                )
            membership = self._client.get(
                f"https://api.telegram.org/bot{secret}/getChatMember",
                params={"chat_id": chat_id, "user_id": identity_result["id"]},
                timeout=10.0,
            )
            membership_payload = membership.json()
        except (httpx.HTTPError, ValueError, TypeError):
            return self._finish(
                "unavailable",
                "Telegram не отвечает. Проверьте подключение к сети и повторите проверку.",
            )
        if not isinstance(membership_payload, dict) or membership_payload.get("ok") is not True:
            return self._finish(
                "failed",
                "Не удалось проверить права бота. Добавьте его администратором канала.",
            )
        member = membership_payload.get("result")
        if not isinstance(member, dict):
            return self._finish("failed", "Telegram не вернул права бота в канале.")
        status = member.get("status")
        if status not in {"creator", "administrator"}:
            return self._finish("failed", "Добавьте бота администратором Telegram-канала.")
        if status == "administrator" and member.get("can_post_messages") is not True:
            return self._finish(
                "failed",
                "Разрешите боту публиковать сообщения в настройках администраторов канала.",
            )
        return self._finish("ok")
