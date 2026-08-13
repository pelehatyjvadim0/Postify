from dataclasses import asdict, replace
from datetime import datetime
from hashlib import sha256
import json

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
            if "selection_policy_version" in payload:
                raise ValueError("Версия политики задаётся системой")
            unknown = set(payload) - set(values)
            if unknown:
                raise ValueError("Некорректные поля секции Конфигурация")
            values.update(payload)
            policy_fields = {
                "selection_rules",
                "topic_terms",
                "topic_exclusion_terms",
                "advertising_terms",
                "hiring_terms",
                "technical_release_terms",
                "practical_terms",
                "selection_freshness_days",
            }
            if policy_fields.intersection(payload):
                canonical = {
                    name: values[name] for name in sorted(policy_fields)
                }
                digest = sha256(
                    json.dumps(
                        canonical,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()[:12]
                values["selection_policy_version"] = f"policy-{digest}"
            updated = replace(
                project,
                configuration=ProjectConfiguration(**values),
                updated_at=now,
            )
        else:
            raise ValueError("Неизвестная секция настроек")
        return self._repository.save(updated)
