from datetime import UTC, datetime

import pytest

from postify.application.projects.manage_rubrics import ManageRubrics, RubricInUse
from postify.domain.projects.models import ProjectRubric


NOW = datetime(2026, 9, 11, 9, tzinfo=UTC)


class MemoryRubrics:
    """Репозиторий одного проекта: чужой project_id отвечает LookupError."""

    def __init__(self, project_id: int = 1) -> None:
        self.project_id = project_id
        self.rubrics = [ProjectRubric(5, project_id, "Кейс", "Разбор задачи", True)]
        self.calls: list[tuple[object, ...]] = []

    def get(self, project_id: int):
        if project_id != self.project_id:
            raise LookupError(project_id)
        return object()

    def list_rubrics(self, project_id: int):
        return tuple(item for item in self.rubrics if item.project_id == project_id)

    def create_rubric(self, project_id, *, name, instructions, enabled, now):
        self.calls.append(("create", project_id, name, instructions, enabled, now))
        created = ProjectRubric(6, project_id, name, instructions, enabled)
        self.rubrics.append(created)
        return created

    def update_rubric(self, project_id, rubric_id, *, values, now):
        self.calls.append(("update", project_id, rubric_id, values, now))
        return ProjectRubric(rubric_id, project_id, "Кейс", "Разбор задачи", True)

    def delete_rubric(self, project_id, rubric_id):
        self.calls.append(("delete", project_id, rubric_id))


def action(repository) -> ManageRubrics:
    return ManageRubrics(repository, clock=lambda: NOW)


def test_create_normalises_text_and_enables_rubric_by_default() -> None:
    repository = MemoryRubrics()

    created = action(repository).create(1, {"name": "  Новости  ", "instructions": "До 500 знаков"})

    assert (created.name, created.enabled) == ("Новости", True)
    assert repository.calls == [("create", 1, "Новости", "До 500 знаков", True, NOW)]


def test_create_rejects_empty_instructions_before_touching_repository() -> None:
    # Поломка: рубрика без инструкций уходит в контекст генерации.
    repository = MemoryRubrics()

    with pytest.raises(ValueError, match="instructions"):
        action(repository).create(1, {"name": "Новости", "instructions": "  "})

    assert repository.calls == []


def test_update_writes_only_the_fields_from_payload() -> None:
    repository = MemoryRubrics()

    action(repository).update(1, 5, {"enabled": False})

    assert repository.calls == [("update", 1, 5, {"enabled": False}, NOW)]


def test_update_of_unknown_rubric_does_not_write() -> None:
    repository = MemoryRubrics()

    with pytest.raises(LookupError):
        action(repository).update(1, 404, {"enabled": False})

    assert repository.calls == []


def test_delete_passes_through_while_plan_slots_do_not_exist() -> None:
    repository = MemoryRubrics()

    action(repository).delete(1, 5)

    assert repository.calls == [("delete", 1, 5)]


def test_delete_reports_conflict_once_plan_slots_reference_the_rubric() -> None:
    # Поломка: удаление рубрики осиротит слоты плана. Точку проверки включает трек контент-плана.
    repository = MemoryRubrics()
    repository.count_rubric_slots = lambda project_id, rubric_id: 3

    with pytest.raises(RubricInUse):
        action(repository).delete(1, 5)

    assert repository.calls == []


def test_foreign_project_id_returns_nothing_and_writes_nothing() -> None:
    repository = MemoryRubrics()

    for call in (
        lambda: action(repository).list(2),
        lambda: action(repository).create(2, {"name": "Чужая", "instructions": "Текст"}),
        lambda: action(repository).update(2, 5, {"enabled": False}),
        lambda: action(repository).delete(2, 5),
    ):
        with pytest.raises(LookupError):
            call()

    assert repository.calls == []
