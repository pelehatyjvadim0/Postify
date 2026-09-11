from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from postify.application.validation.models import ProjectRule


class RulesRepository(Protocol):
    def list_rules(self, project_id: int, *, enabled_only: bool = False) -> Sequence[ProjectRule]: ...

    def replace_rules(self, project_id: int, rules: Sequence[ProjectRule]) -> Sequence[ProjectRule]: ...
