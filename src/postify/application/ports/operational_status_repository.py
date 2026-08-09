from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from postify.domain.observability.models import RawOperationalSnapshot


class OperationalStatusRepository(Protocol):
    def snapshot(self, *, day: date, day_start: datetime, day_end: datetime, limit: int = 10) -> RawOperationalSnapshot: ...
