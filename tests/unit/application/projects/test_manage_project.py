from datetime import UTC, datetime

import pytest

from postify.application.projects.manage_project import (
    DEFAULT_AUDIENCE,
    DEFAULT_LANGUAGE,
    ManageProject,
)
from postify.domain.projects.models import ContentProject
from tests.unit.domain.projects.test_models import configuration


NOW = datetime(2026, 9, 11, 9, tzinfo=UTC)
LATER = datetime(2026, 9, 11, 10, tzinfo=UTC)


def project() -> ContentProject:
    return ContentProject(
        1,
        "Старое название",
        "Старое название",
        "ru",
        "Команды",
        "Europe/Moscow",
        configuration(),
        NOW,
        NOW,
    )


class MemoryProjects:
    def __init__(self, existing: ContentProject | None = None) -> None:
        self.project = existing
        self.created: dict[str, object] | None = None
        self.deleted: list[int] = []

    def get(self, project_id: int) -> ContentProject:
        if self.project is None or self.project.id != project_id:
            raise LookupError(project_id)
        return self.project

    def create(self, **values) -> ContentProject:
        self.created = values
        self.project = ContentProject(
            1,
            values["name"],
            values["topic"],
            values["language"],
            values["audience"],
            values["timezone"],
            values["configuration"],
            values["now"],
            values["now"],
            values["owner_id"],
        )
        return self.project

    def save(self, updated: ContentProject) -> ContentProject:
        self.project = updated
        return updated

    def delete(self, project_id: int) -> None:
        self.deleted.append(project_id)


def action(repository: MemoryProjects) -> ManageProject:
    return ManageProject(repository, clock=lambda: LATER)


def test_create_fills_defaults_for_everything_except_name_and_timezone() -> None:
    repository = MemoryProjects()

    created = ManageProject(repository, clock=lambda: NOW).create(
        {"name": "  Агротех  ", "timezone": "Europe/Moscow"}, owner_id=7
    )

    assert created.name == "Агротех"
    assert created.timezone == "Europe/Moscow"
    assert (created.language, created.audience) == (DEFAULT_LANGUAGE, DEFAULT_AUDIENCE)
    assert created.configuration.tone == "Нейтральный"
    assert repository.created["now"] == NOW
    assert created.owner_id == 7


def test_create_rejects_unknown_timezone_before_writing() -> None:
    # Поломка: невалидный часовой пояс ложится в базу и падает только при чтении.
    repository = MemoryProjects()

    with pytest.raises(ValueError, match="часовой пояс"):
        action(repository).create(
            {"name": "Агротех", "timezone": "Europe/Нигде"}, owner_id=7
        )

    assert repository.created is None


def test_update_changes_editable_fields_and_keeps_configuration_limits() -> None:
    repository = MemoryProjects(project())

    updated = action(repository).update(
        1,
        {
            "name": "Новая редакция",
            "language": "en",
            "audience": "Продуктовые команды",
            "tone": "Дружелюбный",
        },
    )

    assert updated.name == "Новая редакция"
    assert updated.audience == "Продуктовые команды"
    assert updated.configuration.tone == "Дружелюбный"
    assert updated.configuration.media_max_bytes == configuration().media_max_bytes
    assert updated.updated_at == LATER


def test_update_rejects_fields_outside_the_contract_without_saving() -> None:
    # Поломка: PUT проектом переписывает лимиты модели или чужие поля.
    repository = MemoryProjects(project())

    with pytest.raises(ValueError, match="Недопустимые поля"):
        action(repository).update(1, {"analysis_model": "gpt-3"})

    assert repository.project == project()


def test_foreign_project_id_is_not_readable_or_editable() -> None:
    repository = MemoryProjects(project())

    with pytest.raises(LookupError):
        action(repository).get(2)
    with pytest.raises(LookupError):
        action(repository).update(2, {"name": "Чужой"})

    assert repository.project == project()


def test_delete_passes_project_to_repository() -> None:
    repository = MemoryProjects(project())

    action(repository).delete(1)

    assert repository.deleted == [1]
