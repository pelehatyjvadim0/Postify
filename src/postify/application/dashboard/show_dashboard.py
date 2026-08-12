from __future__ import annotations

from datetime import date, datetime

from postify.application.ports.dashboard_repository import DashboardRepository


class ShowDashboard:
    def __init__(self, repository: DashboardRepository) -> None:
        self._repository = repository

    def execute(
        self, project_id: int, day: date, day_start: datetime, day_end: datetime
    ):
        return self._repository.overview(project_id, day, day_start, day_end)
