"""Проверка канала проекта у провайдера и запись наблюдаемого статуса."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from postify.application.projects.manage_channel import channel_view


class CheckChannel:
    """Дёргает провайдера и сохраняет результат проверки канала проекта."""

    def __init__(self, repository, cipher, checker, *, clock: Callable[[], datetime]) -> None:
        self._repository = repository
        self._cipher = cipher
        self._checker = checker
        self._clock = clock

    def execute(self, project_id: int) -> dict[str, object]:
        self._repository.get(project_id)
        channel = self._repository.get_channel(project_id)
        if channel is None:
            raise LookupError(project_id)
        connection, encrypted_secret = channel
        if not isinstance(encrypted_secret, str) or self._cipher is None:
            raise RuntimeError("secret_storage_unavailable")
        status = self._checker.check(
            connection.configuration, self._cipher.decrypt(encrypted_secret)
        )
        self._repository.set_channel_status(project_id, status, self._clock())
        view = channel_view(connection)
        # Статус берём у проверки: в connection лежит ещё дочитанное значение.
        view["status"] = status
        view["reason"] = getattr(self._checker, "last_reason", "")
        return view
