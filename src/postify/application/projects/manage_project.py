"""Сценарии жизненного цикла проекта: создание, правка, удаление.

Проект равен одному Telegram-каналу и заводится пользователем через API, а не
из переменных окружения. Поэтому всё, что нельзя спросить в форме создания,
берётся из значений по умолчанию этого модуля.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from postify.domain.projects.models import ContentProject, ProjectConfiguration


# Форма создания спрашивает только название и часовой пояс, остальное проект
# получает отсюда и правит в настройках.
DEFAULT_LANGUAGE = "ru"
DEFAULT_AUDIENCE = "Подписчики канала"
DEFAULT_MEDIA_MAX_BYTES = 10_000_000
DEFAULT_ANALYSIS_TIMEOUT_SECONDS = 60

CREATE_FIELDS = frozenset({"name", "timezone"})
EDITABLE_FIELDS = frozenset(
    {
        "name", "timezone", "language", "audience", "tone", "project_prompt",
        "publication_mode", "generation_lead_minutes", "media_reuse_days", "media_reuse_blocked",
    }
)

# Идентификатор черновика: проверить инварианты домена надо до вставки, а
# настоящий id выдаёт база.
_DRAFT_ID = 1


class ManageProject:
    """Единственная точка изменения проекта для веб-слоя."""

    def __init__(self, repository, *, clock: Callable[[], datetime]) -> None:
        self._repository = repository
        self._clock = clock

    def list(self, *, owner_id: int) -> tuple[ContentProject, ...]:
        return self._repository.list_projects(owner_id=owner_id)

    def get(self, project_id: int) -> ContentProject:
        return self._repository.get(project_id)

    def create(
        self, payload: dict[str, object], *, owner_id: int
    ) -> ContentProject:
        """Заводит проект на указанного владельца по названию и часовому поясу."""
        self._reject_unknown(payload, CREATE_FIELDS)
        if "name" not in payload:
            raise ValueError("Название проекта обязательно")
        if "timezone" not in payload:
            raise ValueError("Часовой пояс проекта обязателен")
        now = self._clock()
        # Черновик отдаёт валидацию и нормализацию домену: в базу уходит уже
        # проверенное значение, а не то, что упадёт при чтении обратно.
        draft = ContentProject(
            _DRAFT_ID,
            payload["name"],
            # Промпт проекта при создании — название канала: форма создания
            # больше ничего не спрашивает, дальше его правят в настройках.
            payload["name"],
            DEFAULT_LANGUAGE,
            DEFAULT_AUDIENCE,
            payload["timezone"],
            ProjectConfiguration(
                media_max_bytes=DEFAULT_MEDIA_MAX_BYTES,
                analysis_timeout_seconds=DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
            ),
            now,
            now,
        )
        return self._repository.create(
            owner_id=owner_id,
            name=draft.name,
            project_prompt=draft.project_prompt,
            language=draft.language,
            audience=draft.audience,
            timezone=draft.timezone,
            configuration=draft.configuration,
            now=now,
        )

    def update(self, project_id: int, payload: dict[str, object]) -> ContentProject:
        """Плоская правка редактируемых полей проекта."""
        self._reject_unknown(payload, EDITABLE_FIELDS)
        project = self._repository.get(project_id)
        configuration = project.configuration
        if "tone" in payload:
            # Тон живёт в конфигурации, но для API это обычное поле проекта.
            configuration = replace(project.configuration, tone=payload["tone"])
        identity = {name: payload[name] for name in payload if name != "tone"}
        updated = replace(
            project,
            **identity,
            configuration=configuration,
            updated_at=self._clock(),
        )
        return self._repository.save(updated)

    def delete(self, project_id: int) -> tuple[str, ...]:
        return self._repository.delete(project_id) or ()

    @staticmethod
    def _reject_unknown(payload: dict[str, object], allowed: frozenset[str]) -> None:
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Недопустимые поля проекта: {', '.join(sorted(unknown))}")
