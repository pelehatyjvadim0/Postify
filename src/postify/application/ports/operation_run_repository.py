from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from postify.domain.observability.models import OperationKind


class OperationRunRepository(Protocol):
    """Журнал длительных операций; UI опрашивает его по operation_id."""

    def start(
        self,
        operation: OperationKind,
        *,
        now: datetime,
        mode: str = "automatic",
        actor: str = "scheduler",
    ) -> int: ...

    def succeed(
        self,
        run_id: int,
        *,
        outcome: str,
        now: datetime,
        result: Mapping[str, object] | None = None,
    ) -> None: ...

    def fail(
        self,
        run_id: int,
        *,
        failure_code: str,
        now: datetime,
        result: Mapping[str, object] | None = None,
    ) -> None: ...
