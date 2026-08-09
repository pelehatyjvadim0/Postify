from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner


runner = CliRunner()


class FakePublishOnce:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def execute(self):
        if self.error is not None:
            raise self.error
        return self.result


@contextmanager
def opened(action):
    yield action


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (SimpleNamespace(outcome="empty", package_id=None, message_id=None), "Слот пуст\n"),
        (SimpleNamespace(outcome="published", package_id=41, message_id=731), "Опубликован пакет 41; message_id=731\n"),
        (SimpleNamespace(outcome="cleanup_completed", package_id=41, message_id=None), "Cleanup завершён для пакета 41\n"),
        (SimpleNamespace(outcome="cleanup_pending", package_id=41, message_id=None), "Cleanup ожидает повтора для пакета 41\n"),
        (SimpleNamespace(outcome="retryable", package_id=41, message_id=None), "Исход доставки пакета 41: retryable\n"),
        (SimpleNamespace(outcome="failed", package_id=41, message_id=None), "Исход доставки пакета 41: failed\n"),
        (SimpleNamespace(outcome="uncertain", package_id=41, message_id=None), "Исход доставки пакета 41: uncertain\n"),
    ],
)
def test_publish_once_prints_each_safe_outcome(monkeypatch, result, expected: str) -> None:
    # Поломка: outcome теряется, маскируется успехом или печатает лишние данные.
    from postify import cli

    monkeypatch.setattr(cli, "Settings", lambda: SimpleNamespace())
    monkeypatch.setattr(cli, "TelegramSettings", lambda: SimpleNamespace())
    monkeypatch.setattr(cli, "open_publish_once", lambda settings, telegram: opened(FakePublishOnce(result)), raising=False)

    completed = runner.invoke(cli.app, ["publish-once"])

    assert completed.exit_code == 0
    assert completed.output == expected


def test_publish_once_validates_settings_before_opening_boundary(monkeypatch) -> None:
    # Поломка: invalid settings раскрывают field/value или открывают publisher.
    from pydantic import BaseModel, Field
    from postify import cli

    class InvalidTelegram(BaseModel):
        token: str = Field(min_length=100)

    calls: list[str] = []

    def invalid_settings():
        return InvalidTelegram(token="SENTINEL-SECRET")

    def forbidden_boundary(*args, **kwargs):
        calls.append("opened")
        raise AssertionError

    monkeypatch.setattr(cli, "Settings", lambda: SimpleNamespace())
    monkeypatch.setattr(cli, "TelegramSettings", invalid_settings)
    monkeypatch.setattr(cli, "open_publish_once", forbidden_boundary, raising=False)

    completed = runner.invoke(cli.app, ["publish-once"])

    assert completed.exit_code != 0
    assert completed.output == "Некорректная конфигурация Telegram\n"
    assert calls == []
    assert "SENTINEL-SECRET" not in completed.output
    assert "Traceback" not in completed.output


def test_publish_once_normalizes_runtime_error_without_secrets(monkeypatch) -> None:
    # Поломка: exception печатает token/URL/caption/path/traceback.
    from postify import cli

    leaked = "123456:SENTINEL-TOKEN https://api.telegram.org/bot/private SECRET-CAPTION /media/private.png"
    monkeypatch.setattr(cli, "Settings", lambda: SimpleNamespace())
    monkeypatch.setattr(cli, "TelegramSettings", lambda: SimpleNamespace())
    monkeypatch.setattr(
        cli,
        "open_publish_once",
        lambda settings, telegram: opened(FakePublishOnce(error=RuntimeError(leaked))),
        raising=False,
    )

    completed = runner.invoke(cli.app, ["publish-once"])

    assert completed.exit_code != 0
    assert completed.output == "Не удалось выполнить Telegram-доставку\n"
    assert "SENTINEL" not in completed.output
    assert "telegram.org" not in completed.output
    assert "Traceback" not in completed.output
