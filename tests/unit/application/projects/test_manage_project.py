from datetime import UTC, datetime

import pytest

from postify.application.projects.manage_project import ManageProject
from postify.domain.projects.models import ContentProject
from tests.unit.domain.projects.test_models import configuration


class MemoryProjects:
    def __init__(self, project: ContentProject) -> None:
        self.project = project

    def get(self, project_id: int) -> ContentProject:
        if self.project.id != project_id:
            raise LookupError(project_id)
        return self.project

    def save(self, project: ContentProject) -> ContentProject:
        self.project = project
        return project


def project() -> ContentProject:
    now = datetime(2026, 8, 12, 8, tzinfo=UTC)
    return ContentProject(
        1,
        "Старое название",
        "AI",
        "ru",
        "Команды",
        "Europe/Moscow",
        configuration(),
        now,
        now,
    )


def test_update_main_changes_only_editable_identity_fields() -> None:
    repository = MemoryProjects(project())
    changed_at = datetime(2026, 8, 12, 9, tzinfo=UTC)

    updated = ManageProject(repository).update(
        1,
        "main",
        {
            "name": "Новая редакция",
            "topic": "Практичная автоматизация",
            "language": "ru",
            "audience": "Продуктовые команды",
            "timezone": "Europe/Moscow",
        },
        now=changed_at,
    )

    assert updated.name == "Новая редакция"
    assert updated.configuration == project().configuration
    assert updated.updated_at == changed_at


def test_update_rejects_unknown_section_without_saving() -> None:
    repository = MemoryProjects(project())

    with pytest.raises(ValueError, match="секция"):
        ManageProject(repository).update(
            1,
            "billing",
            {},
            now=datetime(2026, 8, 12, 9, tzinfo=UTC),
        )

    assert repository.project == project()


def test_update_configuration_revalidates_technical_limits() -> None:
    repository = MemoryProjects(project())

    with pytest.raises(ValueError, match="analysis_batch_size"):
        ManageProject(repository).update(
            1,
            "configuration",
            {"analysis_batch_size": 0},
            now=datetime(2026, 8, 12, 9, tzinfo=UTC),
        )
