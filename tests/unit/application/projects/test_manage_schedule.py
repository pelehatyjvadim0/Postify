from datetime import UTC, datetime

from postify.application.projects.manage_schedule import ManageProjectSchedule


NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)


class Repository:
    def __init__(self) -> None:
        self.calls = []

    def get(self, project_id: int):
        self.calls.append(("get", project_id))
        return object()

    def update_schedules(self, project_id, sources, routes, now):
        self.calls.append(("update_schedules", project_id, sources, routes, now))
        return {"sources": len(sources), "routes": len(routes)}


def test_schedule_action_uses_one_atomic_repository_command_with_only_schedule_fields() -> None:
    # Break caught: one settings section orchestrates multiple persistence calls with unchanged resource DTO fields.
    repository = Repository()
    action = ManageProjectSchedule(repository)

    result = action.update(
        41,
        {
            "sources": [{"id": 1, "schedule": "0 8 * * *"}],
            "routes": [{
                "id": 9,
                "autopublish": False,
                "slots": ["08:30", "13:30", "18:30"],
            }],
        },
        now=NOW,
    )

    assert result == {"sources": 1, "routes": 1}
    assert repository.calls == [
        ("get", 41),
        (
            "update_schedules",
            41,
            ({"id": 1, "schedule": "0 8 * * *"},),
            ({"id": 9, "autopublish": False, "slots": ("08:30", "13:30", "18:30")},),
            NOW,
        ),
    ]
