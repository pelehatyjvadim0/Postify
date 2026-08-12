from postify.application.ports.project_repository import ProjectRepository


class ManageProjectSchedule:
    """Persist every schedule editor as one repository transaction."""

    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    def update(
        self,
        project_id: int,
        payload: dict[str, object],
        *,
        now,
    ) -> dict[str, int]:
        self._repository.get(project_id)
        sources = tuple(
            {"id": item["id"], "schedule": item["schedule"]}
            for item in payload["sources"]
        )
        routes = tuple(
            {
                "id": item["id"],
                "autopublish": item["autopublish"],
                "slots": tuple(item["slots"]),
            }
            for item in payload["routes"]
        )
        return self._repository.update_schedules(project_id, sources, routes, now)
