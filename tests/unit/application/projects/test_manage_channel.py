from datetime import UTC, datetime

import pytest

from postify.application.projects.manage_channel import (
    RemoveProjectChannel,
    SetProjectChannel,
)
from postify.domain.projects.models import ChannelConnection


NOW = datetime(2026, 9, 11, 9, tzinfo=UTC)


class MemoryChannels:
    def __init__(self, project_id: int = 1) -> None:
        self.project_id = project_id
        self.saved: dict[str, object] | None = None
        self.deleted: list[int] = []

    def get(self, project_id: int):
        if project_id != self.project_id:
            raise LookupError(project_id)
        return object()

    def save_channel(self, project_id, *, provider, name, configuration, encrypted_secret, now):
        self.saved = {
            "project_id": project_id,
            "provider": provider,
            "configuration": configuration,
            "encrypted_secret": encrypted_secret,
            "now": now,
        }
        return ChannelConnection(
            1, project_id, provider, name, True, configuration, True, "configured"
        )

    def delete_channel(self, project_id: int) -> None:
        self.deleted.append(project_id)

    def get_channel(self, project_id: int):
        return None


class Cipher:
    def encrypt(self, value: str) -> str:
        return f"enc:{value}"


def test_set_channel_encrypts_token_and_never_returns_it() -> None:
    # Поломка: токен бота утекает в ответ API или ложится в базу открытым.
    repository = MemoryChannels()

    view = SetProjectChannel(repository, Cipher(), clock=lambda: NOW).execute(
        1, bot_token="  123:secret  ", chat_id=" @agrotech "
    )

    assert view == {"configured": True, "chat_id": "@agrotech", "status": "configured"}
    assert repository.saved["encrypted_secret"] == "enc:123:secret"
    assert repository.saved["provider"] == "telegram"
    assert "123:secret" not in repr(view)


def test_set_channel_requires_token_and_chat_id() -> None:
    repository = MemoryChannels()
    action = SetProjectChannel(repository, Cipher(), clock=lambda: NOW)

    with pytest.raises(ValueError, match="токен"):
        action.execute(1, bot_token="   ", chat_id="@agrotech")
    with pytest.raises(ValueError, match="username"):
        action.execute(1, bot_token="123:secret", chat_id="")

    assert repository.saved is None


def test_set_channel_fails_when_secret_storage_is_unavailable() -> None:
    repository = MemoryChannels()

    with pytest.raises(RuntimeError, match="secret_storage_unavailable"):
        SetProjectChannel(repository, None, clock=lambda: NOW).execute(
            1, bot_token="123:secret", chat_id="@agrotech"
        )

    assert repository.saved is None


def test_foreign_project_id_neither_sets_nor_removes_channel() -> None:
    repository = MemoryChannels()

    with pytest.raises(LookupError):
        SetProjectChannel(repository, Cipher(), clock=lambda: NOW).execute(
            2, bot_token="123:secret", chat_id="@agrotech"
        )
    with pytest.raises(LookupError):
        RemoveProjectChannel(repository).execute(2)

    assert repository.saved is None
    assert repository.deleted == []


def test_remove_channel_deletes_connection_with_its_secret() -> None:
    repository = MemoryChannels()

    RemoveProjectChannel(repository).execute(1)

    assert repository.deleted == [1]
