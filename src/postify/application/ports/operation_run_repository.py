from __future__ import annotations

from datetime import datetime
from typing import Protocol

from postify.domain.observability.models import OperationKind


class OperationRunRepository(Protocol):
    def start(self, operation: OperationKind, *, now: datetime, mode: str = "automatic", actor: str = "scheduler") -> int: ...
    def succeed(self, run_id: int, *, outcome: str, now: datetime, codex_model: str | None = None, codex_reasoning_effort: str | None = None, materials_taken: int = 0, packages_created: int = 0) -> None: ...
    def fail(self, run_id: int, *, failure_code: str, now: datetime, codex_model: str | None = None, codex_reasoning_effort: str | None = None, materials_taken: int = 0, packages_created: int = 0) -> None: ...
