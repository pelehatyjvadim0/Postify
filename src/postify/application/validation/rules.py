from __future__ import annotations

from postify.application.validation.derive_rules import derive_rules
from postify.application.validation.models import ProjectRule


class ManageRules:
    """Чтение и атомарная замена чеклиста проекта, как в PUT-контракте."""

    def __init__(self, repository):
        self.repository = repository

    def list(self, project_id: int) -> tuple[ProjectRule, ...]:
        return tuple(self.repository.list_rules(project_id))

    def replace(self, project_id: int, rules) -> tuple[ProjectRule, ...]:
        checked = []
        for position, item in enumerate(rules):
            text = str(item.get("text", "")).strip()
            severity = item.get("severity", "block")
            origin = item.get("origin", "manual")
            if not text:
                raise ValueError("Текст правила обязателен")
            if severity not in {"block", "warn"}:
                raise ValueError("Неизвестная строгость правила")
            if origin not in {"derived", "manual"}:
                raise ValueError("Неизвестное происхождение правила")
            checked.append(ProjectRule(0, project_id, text, severity, bool(item.get("enabled", True)), origin, position))
        return tuple(self.repository.replace_rules(project_id, checked))


class DeriveRules:
    """Выдаёт предложение чеклиста, не сохраняя его."""

    def __init__(self, gateway):
        self.gateway = gateway

    def execute(self, *, project_id: int, project_prompt: str, user_id: int | None = None):
        return derive_rules(self.gateway, project_id=project_id, project_prompt=project_prompt, user_id=user_id)
