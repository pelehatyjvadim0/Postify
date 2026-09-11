"""Рубрики проекта: форма и редакционные правила будущего поста.

Рубрики заменили прежние «форматы контента»: маршрут «формат → канал» стал не
нужен, потому что проект равен одному каналу.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from postify.domain.projects.models import ProjectRubric


RUBRIC_FIELDS = frozenset({"name", "instructions", "enabled"})

# Идентификатор черновика: инварианты домена проверяются до вставки, настоящий
# id выдаёт база.
_DRAFT_ID = 1


class RubricInUse(RuntimeError):
    """Рубрику нельзя удалить: на неё ссылаются слоты контент-плана (409)."""


class ManageRubrics:
    """CRUD рубрик одного проекта."""

    def __init__(self, repository, *, clock: Callable[[], datetime]) -> None:
        self._repository = repository
        self._clock = clock

    def list(self, project_id: int) -> tuple[ProjectRubric, ...]:
        self._project(project_id)
        return self._repository.list_rubrics(project_id)

    def create(self, project_id: int, payload: dict[str, object]) -> ProjectRubric:
        self._project(project_id)
        self._reject_unknown(payload)
        for field in ("name", "instructions"):
            if field not in payload:
                raise ValueError(f"Поле {field} обязательно")
        draft = ProjectRubric(
            _DRAFT_ID,
            project_id,
            payload["name"],
            payload["instructions"],
            payload.get("enabled", True),
        )
        return self._repository.create_rubric(
            project_id,
            name=draft.name,
            instructions=draft.instructions,
            enabled=draft.enabled,
            now=self._clock(),
        )

    def update(
        self, project_id: int, rubric_id: int, payload: dict[str, object]
    ) -> ProjectRubric:
        """Частичная правка: проверяем домен на слитом значении, пишем изменённое."""
        self._project(project_id)
        self._reject_unknown(payload)
        draft = replace(self._rubric(project_id, rubric_id), **payload)
        values = {name: getattr(draft, name) for name in payload}
        return self._repository.update_rubric(
            project_id, rubric_id, values=values, now=self._clock()
        )

    def delete(self, project_id: int, rubric_id: int) -> None:
        self._project(project_id)
        self._ensure_not_in_use(project_id, rubric_id)
        self._repository.delete_rubric(project_id, rubric_id)

    def _ensure_not_in_use(self, project_id: int, rubric_id: int) -> None:
        """Единственная точка проверки ссылок на рубрику.

        Таблицы слотов плана пока нет, проверять нечего. Трек контент-плана
        добавит в репозиторий ``count_rubric_slots`` — и отсюда начнёт
        подниматься ``RubricInUse``, которому контракт сопоставляет 409
        ``rubric_in_use``.
        """
        count = getattr(self._repository, "count_rubric_slots", None)
        if count is not None and count(project_id, rubric_id):
            raise RubricInUse(rubric_id)

    def _project(self, project_id: int) -> None:
        """Чужой или несуществующий проект обязан упасть LookupError → 404."""
        self._repository.get(project_id)

    def _rubric(self, project_id: int, rubric_id: int) -> ProjectRubric:
        for item in self._repository.list_rubrics(project_id):
            if item.id == rubric_id:
                return item
        raise LookupError(rubric_id)

    @staticmethod
    def _reject_unknown(payload: dict[str, object]) -> None:
        unknown = set(payload) - RUBRIC_FIELDS
        if unknown:
            raise ValueError(f"Недопустимые поля рубрики: {', '.join(sorted(unknown))}")
