"""Сборка действий входа в один объект.

Веб-слой и цикл опроса бота работают с одним экземпляром: он держит
репозиторий, часы, список разрешённых и имя бота.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from postify.application.auth.actions import (
    CompleteLogin,
    HandleBotDecision,
    HandleBotStart,
    Logout,
    ResolveSession,
    StartLogin,
)
from postify.domain.auth.models import TelegramUnavailable


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuthService:
    """Фасад входа: действия плюс имя бота для диплинка."""

    def __init__(
        self,
        repository,
        *,
        allowlist: frozenset[str] = frozenset(),
        bot_username: str | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.repository = repository
        self.clock = clock
        # Имя из настройки известно сразу; иначе его подставит getMe при старте
        # цикла опроса, до этого вход отвечает telegram_unavailable.
        self._bot_username = _normalise_username(bot_username)
        self.start_login = StartLogin(
            repository, username=self.bot_username, clock=clock
        )
        self.handle_bot_start = HandleBotStart(repository, clock=clock)
        self.handle_bot_decision = HandleBotDecision(repository, clock=clock)
        self.complete_login = CompleteLogin(
            repository, allowlist=allowlist, clock=clock
        )
        self.resolve_session = ResolveSession(repository, clock=clock)
        self.logout = Logout(repository)

    def bot_username(self) -> str:
        if not self._bot_username:
            raise TelegramUnavailable()
        return self._bot_username

    def set_bot_username(self, username: str | None) -> None:
        """Цикл опроса подставляет имя, полученное из getMe."""
        resolved = _normalise_username(username)
        if resolved:
            self._bot_username = resolved

    def owns_project(self, *, user_id: int, project_id: int) -> bool:
        """Владение проектом. Чужой и несуществующий проект неотличимы."""
        return self.repository.project_owner(project_id) == user_id


def _normalise_username(value: str | None) -> str:
    """Имя бота без @; мусор считается отсутствующим именем."""
    username = (value or "").lstrip("@")
    allowed = username.replace("_", "").isalnum() and username.isascii()
    return username if allowed and 5 <= len(username) <= 32 else ""
