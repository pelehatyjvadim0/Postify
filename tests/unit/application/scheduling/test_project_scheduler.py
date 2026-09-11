from datetime import UTC, datetime

from postify.application.scheduling.project_scheduler import (
    ProjectSchedule,
    ProjectScheduler,
    ScheduledCommand,
)


class Repository:
    def __init__(
        self,
        publications: tuple[ScheduledCommand, ...] = (),
        generations: tuple[ScheduledCommand, ...] = (),
    ) -> None:
        self.publications = publications
        self.generations = generations
        self.recovered_at = None
        self.pending: tuple[ScheduledCommand, ...] = ()

    def recover_stale_deliveries(self, *, now):
        self.recovered_at = now
        return 0

    def claim_pending(self, *, now):
        return self.pending

    def list_schedules(self):
        return (ProjectSchedule(project_id=1, timezone="UTC"),)

    def due_publications(self, *, project_id, now):
        return self.publications

    def due_generations(self, *, project_id, now):
        return self.generations

    def accept(self, command):
        return command

    def claim_job(self, job_id, *, now):
        return next(
            (
                item
                for item in (*self.generations, *self.publications)
                if item.job_id == job_id
            ),
            None,
        )


def test_due_approved_post_keeps_its_utc_slot_and_target() -> None:
    planned = ScheduledCommand(
        1, "publish_once", datetime(2026, 9, 5, 9, tzinfo=UTC), post_id=41, job_id=17
    )
    repository = Repository((planned,))
    submitted = []

    commands = ProjectScheduler(repository, submitted.append).tick(
        datetime(2026, 9, 5, 10, tzinfo=UTC)
    )

    assert commands == (planned,)
    assert submitted == [planned]


def test_stale_delivery_recovery_runs_before_due_plan_claim() -> None:
    repository = Repository()

    ProjectScheduler(repository, lambda command: None).tick(
        datetime(2026, 9, 5, 10, tzinfo=UTC)
    )

    assert repository.recovered_at == datetime(2026, 9, 5, 10, tzinfo=UTC)


def test_recovered_jobs_run_before_the_schedule_is_read() -> None:
    # Задача, пережившая перезапуск, обязана уйти в работу без нового слота.
    recovered = ScheduledCommand(
        1, "publish_once", datetime(2026, 9, 5, 9, tzinfo=UTC), post_id=7, job_id=3
    )
    repository = Repository()
    repository.pending = (recovered,)
    submitted = []

    commands = ProjectScheduler(repository, submitted.append).tick(
        datetime(2026, 9, 5, 10, tzinfo=UTC)
    )

    assert commands == (recovered,)
    assert submitted == [recovered]


def test_lost_lease_drops_the_command() -> None:
    # claim_job вернул None: слот занял другой процесс, запускать нечего.
    planned = ScheduledCommand(
        1, "publish_once", datetime(2026, 9, 5, 9, tzinfo=UTC), post_id=41, job_id=99
    )
    repository = Repository((planned,))
    repository.publications = (planned,)
    submitted = []

    class LostLease(Repository):
        def claim_job(self, job_id, *, now):
            return None

    lost = LostLease((planned,))
    commands = ProjectScheduler(lost, submitted.append).tick(
        datetime(2026, 9, 5, 10, tzinfo=UTC)
    )

    assert commands == ()
    assert submitted == []


def test_naive_now_is_rejected() -> None:
    repository = Repository()
    try:
        ProjectScheduler(repository, lambda command: None).tick(
            datetime(2026, 9, 5, 10)
        )
    except ValueError as error:
        assert "timezone" in str(error)
    else:
        raise AssertionError("Планировщик обязан требовать таймзону")


def test_slot_due_for_generation_is_queued_as_a_generate_command() -> None:
    # Само выполнение приносит трек агента: планировщик обязан только поставить
    # задачу и не перепутать её цель — у генерации это слот, а не пост.
    planned = ScheduledCommand(
        1, "generate_post", datetime(2026, 9, 5, 9, tzinfo=UTC), slot_id=41, job_id=8
    )
    repository = Repository(generations=(planned,))
    submitted = []

    commands = ProjectScheduler(repository, submitted.append).tick(
        datetime(2026, 9, 5, 10, tzinfo=UTC)
    )

    assert commands == (planned,)
    assert submitted == [planned]
    assert planned.post_id is None
