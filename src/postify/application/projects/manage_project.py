from dataclasses import asdict, replace
from datetime import datetime

from postify.application.ports.project_repository import ProjectRepository
from postify.domain.projects.models import ContentProject, ProjectConfiguration


class ManageProject:
    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    def get(self, project_id: int) -> ContentProject:
        return self._repository.get(project_id)

    def update(
        self,
        project_id: int,
        section: str,
        payload: dict[str, object],
        *,
        now: datetime,
    ) -> ContentProject:
        project = self._repository.get(project_id)
        if section == "main":
            allowed = {"name", "topic", "language", "audience", "timezone"}
            if set(payload) != allowed:
                raise ValueError("Некорректные поля секции Основное")
            updated = replace(project, **payload, updated_at=now)
        elif section == "configuration":
            values = asdict(project.configuration)
            unknown = set(payload) - set(values)
            if unknown:
                raise ValueError("Некорректные поля секции Конфигурация")
            values.update(payload)
            updated = replace(
                project,
                configuration=ProjectConfiguration(**values),
                updated_at=now,
            )
        else:
            raise ValueError("Неизвестная секция настроек")
        return self._repository.save(updated)
