"""CLI системного промпта сервера.

Через API его не показать и не изменить (раздел 13 контракта), поэтому эти
команды — единственный способ править промпт, кроме прямого доступа к базе.
"""

from __future__ import annotations

from datetime import datetime

from typer.testing import CliRunner

from postify import cli


class MemoryPrompts:
    """Хранилище промптов в памяти с тем же контрактом, что у SQLAlchemy-версии."""

    def __init__(self, value: str = "") -> None:
        self.value = value
        self.updated_at: datetime | None = None

    def system_prompt(self) -> str:
        return self.value

    def set_system_prompt(self, prompt: str, *, now: datetime) -> str:
        self.value = prompt
        self.updated_at = now
        return prompt


def run(monkeypatch, repository: MemoryPrompts, *args: str):
    monkeypatch.setattr(cli, "prompt_repository", lambda: repository)
    return CliRunner().invoke(cli.app, list(args))


def test_show_prints_the_stored_system_prompt(monkeypatch) -> None:
    repository = MemoryPrompts("Ты SMM-специалист.")

    result = run(monkeypatch, repository, "system-prompt", "show")

    assert result.exit_code == 0
    assert "Ты SMM-специалист." in result.output


def test_show_does_not_fail_when_the_prompt_was_never_set(monkeypatch) -> None:
    result = run(monkeypatch, MemoryPrompts(), "system-prompt", "show")

    assert result.exit_code == 0


def test_set_replaces_the_prompt_entirely(monkeypatch) -> None:
    # Поломка: команда дописывает текст вместо замены, и промпт растёт при
    # каждой правке.
    repository = MemoryPrompts("Старый промпт")

    result = run(monkeypatch, repository, "system-prompt", "set", "Новый промпт")

    assert result.exit_code == 0
    assert repository.value == "Новый промпт"
    assert repository.updated_at is not None
    assert repository.updated_at.tzinfo is not None


def test_set_requires_the_text(monkeypatch) -> None:
    repository = MemoryPrompts("Старый промпт")

    result = run(monkeypatch, repository, "system-prompt", "set")

    assert result.exit_code != 0
    assert repository.value == "Старый промпт"
