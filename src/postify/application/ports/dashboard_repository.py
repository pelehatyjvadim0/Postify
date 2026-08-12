from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from postify.application.dashboard.models import (
    DashboardOverview,
    Material,
    Operation,
    PackageDetail,
    PackageSummary,
    Publication,
    QueueSlot,
)


class DashboardRepository(Protocol):
    def overview(
        self, project_id: int, day: date, day_start: datetime, day_end: datetime
    ) -> DashboardOverview: ...

    def materials(
        self,
        project_id: int,
        status: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Material, ...]: ...

    def packages(
        self,
        project_id: int,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[PackageSummary, ...]: ...

    def package(self, project_id: int, package_id: int) -> PackageDetail: ...

    def queue(self, project_id: int, day: date) -> tuple[QueueSlot, ...]: ...

    def publications(
        self, project_id: int, limit: int = 50, offset: int = 0
    ) -> tuple[Publication, ...]: ...

    def operations(
        self, project_id: int, limit: int = 50, offset: int = 0
    ) -> tuple[Operation, ...]: ...
