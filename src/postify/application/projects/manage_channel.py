"""Канал проекта: подключение и отключение единственного Telegram-канала.

Токен бота принимается, шифруется и наружу не возвращается никогда — в ответе
только признак того, что канал настроен.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from postify.domain.projects.models import ChannelConnection


CHANNEL_PROVIDER = "telegram"
CHANNEL_NAME = "Telegram"


def channel_view(connection: ChannelConnection | None) -> dict[str, object]:
    """Публичное представление канала: без токена и без шифротекста."""
    if connection is None:
        return {"configured": False, "chat_id": "", "status": "unconfigured"}
    return {
        "configured": connection.secret_configured,
        "chat_id": connection.configuration.get("chat_id", ""),
        "status": connection.connection_status,
    }


class SetProjectChannel:
    """Привязывает Telegram-канал к проекту (один канал на проект)."""

    def __init__(self, repository, cipher, *, clock: Callable[[], datetime]) -> None:
        self._repository = repository
        self._cipher = cipher
        self._clock = clock

    def execute(
        self, project_id: int, *, bot_token: str | None = None, chat_id: str
    ) -> dict[str, object]:
        self._repository.get(project_id)
        if self._cipher is None:
            raise RuntimeError("secret_storage_unavailable")
        token = bot_token.strip() if isinstance(bot_token, str) else ""
        if not token:
            existing = self._repository.get_channel(project_id)
            if existing is None or not existing[1]:
                raise ValueError("Нужен токен бота")
        target = " ".join(str(chat_id).split()) if chat_id is not None else ""
        if not target:
            raise ValueError("Нужен @username канала")
        connection = self._repository.save_channel(
            project_id,
            provider=CHANNEL_PROVIDER,
            name=CHANNEL_NAME,
            configuration={"chat_id": target},
            encrypted_secret=self._cipher.encrypt(token) if token else None,
            now=self._clock(),
        )
        return channel_view(connection)


class RemoveProjectChannel:
    """Отключает канал проекта вместе с его секретом."""

    def __init__(self, repository) -> None:
        self._repository = repository

    def execute(self, project_id: int) -> None:
        self._repository.get(project_id)
        self._repository.delete_channel(project_id)
