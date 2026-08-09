from __future__ import annotations

from datetime import datetime
from typing import Protocol

from postify.domain.observability.models import OperationKind


class OperationRunRepository(Protocol):
    def start(self, operation: OperationKind, *, now: datetime) -> int: ...
    def succeed(self, run_id: int, *, outcome: str, now: datetime) -> None: ...
    def fail(self, run_id: int, *, failure_code: str, now: datetime) -> None: ...
