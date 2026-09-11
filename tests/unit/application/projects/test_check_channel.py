from __future__ import annotations

from datetime import UTC, datetime

import pytest

from postify.application.projects.check_channel import CheckChannel
from postify.domain.projects.models import ChannelConnection


NOW = datetime(2026, 9, 11, 10, tzinfo=UTC)


def connection(project_id: int = 1) -> ChannelConnection:
    return ChannelConnection(
        1, project_id, "telegram", "Telegram", True, {"chat_id": "@agrotech"}, True, "configured"
    )


_CONFIGURED = "configured"


class Repository:
    def __init__(self, channel: object = _CONFIGURED) -> None:
        self._channel = (connection(), "cipher") if channel == _CONFIGURED else channel
        self.statuses: list[tuple[int, str, datetime]] = []

    def get(self, project_id: int):
        if project_id != 1:
            raise LookupError(project_id)
        return object()

    def get_channel(self, project_id: int):
        return self._channel

    def set_channel_status(self, project_id: int, status: str, now: datetime) -> None:
        self.statuses.append((project_id, status, now))


class Cipher:
    def decrypt(self, value: str) -> str:
        assert value == "cipher"
        return "123:secret"


class Checker:
    def __init__(self, status: str = "ok", reason: str = "") -> None:
        self.status = status
        self.last_reason = reason
        self.seen: list[tuple[dict[str, object], str]] = []

    def check(self, configuration: dict[str, object], secret: str) -> str:
        self.seen.append((configuration, secret))
        return self.status


def test_check_decrypts_project_channel_and_persists_observed_status() -> None:
    # Поломка: UI показывает настроенный канал проверенным, не вызвав провайдера.
    repository = Repository()
    checker = Checker()

    result = CheckChannel(repository, Cipher(), checker, clock=lambda: NOW).execute(1)

    assert checker.seen == [({"chat_id": "@agrotech"}, "123:secret")]
    assert result == {
        "configured": True,
        "chat_id": "@agrotech",
        "status": "ok",
        "reason": "",
    }
    assert repository.statuses == [(1, "ok", NOW)]


def test_failed_check_returns_reason_and_stores_failure() -> None:
    repository = Repository()
    checker = Checker("failed", "Добавьте бота администратором Telegram-канала.")

    result = CheckChannel(repository, Cipher(), checker, clock=lambda: NOW).execute(1)

    assert result["status"] == "failed"
    assert result["reason"].startswith("Добавьте бота")
    assert repository.statuses == [(1, "failed", NOW)]


def test_project_without_channel_is_not_checked() -> None:
    repository = Repository(channel=None)

    with pytest.raises(LookupError):
        CheckChannel(repository, Cipher(), Checker(), clock=lambda: NOW).execute(1)

    assert repository.statuses == []


def test_channel_without_stored_secret_is_not_checked() -> None:
    repository = Repository(channel=(connection(), None))

    with pytest.raises(RuntimeError, match="secret_storage_unavailable"):
        CheckChannel(repository, Cipher(), Checker(), clock=lambda: NOW).execute(1)

    assert repository.statuses == []


def test_foreign_project_id_is_not_checked() -> None:
    repository = Repository()

    with pytest.raises(LookupError):
        CheckChannel(repository, Cipher(), Checker(), clock=lambda: NOW).execute(2)

    assert repository.statuses == []
