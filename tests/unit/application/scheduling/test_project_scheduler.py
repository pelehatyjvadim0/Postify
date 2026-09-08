from datetime import UTC, datetime

from postify.application.scheduling.project_scheduler import (
    ProjectSchedule,
    ProjectScheduler,
    ScheduledCommand,
    SourceSchedule,
)


class Repository:
    def __init__(self, publications: tuple[ScheduledCommand, ...] = ()) -> None:
        self.publications = publications
        self.recovered_at = None

    def recover_stale_deliveries(self, *, now):
        self.recovered_at = now
        return 0

    def claim_pending(self, *, now):
        return ()

    def list_schedules(self):
        return (ProjectSchedule(1, "UTC", (SourceSchedule(True, "0 9 * * *"),)),)

    def due_publications(self, *, project_id, now):
        return self.publications

    def accept(self, command):
        return command

    def claim_job(self, job_id, *, now):
        return next((item for item in self.publications if item.job_id == job_id), ScheduledCommand(1, "run_once", now, job_id=job_id))


def test_due_approved_package_keeps_its_utc_date_route_and_target() -> None:
    planned = ScheduledCommand(1, "publish_once", datetime(2026, 9, 5, 9, tzinfo=UTC), route_id=8, package_id=41, job_id=17)
    repository = Repository((planned,))
    submitted = []

    commands = ProjectScheduler(repository, submitted.append).tick(datetime(2026, 9, 5, 10, tzinfo=UTC))

    assert commands[0] == planned
    assert submitted[0] == planned


def test_stale_delivery_recovery_runs_before_due_plan_claim() -> None:
    repository = Repository()

    ProjectScheduler(repository, lambda command: None).tick(datetime(2026, 9, 5, 10, tzinfo=UTC))

    assert repository.recovered_at == datetime(2026, 9, 5, 10, tzinfo=UTC)
