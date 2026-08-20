from __future__ import annotations

from datetime import UTC, date, datetime


def test_show_dashboard_forwards_explicit_project_and_day_boundaries() -> None:
    # Поломка: action скрывает project/day boundaries и читает другой срез.
    from postify.application.dashboard.show_dashboard import ShowDashboard

    class Repository:
        def __init__(self) -> None:
            self.arguments = None

        def overview(self, project_id, day, day_start, day_end):
            self.arguments = (project_id, day, day_start, day_end)
            return "overview"

    repository = Repository()
    day = date(2026, 8, 12)
    start = datetime(2026, 8, 11, 21, tzinfo=UTC)
    end = datetime(2026, 8, 12, 21, tzinfo=UTC)

    assert ShowDashboard(repository).execute(7, day, start, end) == "overview"
    assert repository.arguments == (7, day, start, end)
