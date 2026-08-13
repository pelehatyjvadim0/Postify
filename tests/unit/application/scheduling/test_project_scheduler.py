from __future__ import annotations

from datetime import UTC, datetime

from postify.application.scheduling.project_scheduler import (
    ProjectSchedule,
    ProjectScheduler,
    RouteSchedule,
    ScheduledCommand,
    SourceSchedule,
)


class ScheduleRepository:
    def __init__(self, schedules: tuple[ProjectSchedule, ...]) -> None:
        self._schedules = schedules
        self.claimed = set()

    def list_schedules(self) -> tuple[ProjectSchedule, ...]:
        return self._schedules

    def claim(self, command) -> bool:
        if command in self.claimed:
            return False
        self.claimed.add(command)
        return True


def _project(
    *,
    timezone: str = "Europe/Moscow",
    sources: tuple[SourceSchedule, ...] = (),
    routes: tuple[RouteSchedule, ...] = (),
) -> ProjectSchedule:
    return ProjectSchedule(
        project_id=41,
        timezone=timezone,
        sources=sources,
        routes=routes,
    )


def test_tick_submits_each_due_command_through_injected_runner() -> None:
    # Поломка: scheduler вычисляет due slots, но обходит общий runner.
    repository = ScheduleRepository(
        (
            _project(
                sources=(SourceSchedule(enabled=True, cron="0 9 * * *"),),
                routes=(
                    RouteSchedule(
                        enabled=True,
                        autopublish=True,
                        slots=("09:00", "14:00", "19:00"),
                    ),
                ),
            ),
        )
    )
    submitted = []
    scheduler = ProjectScheduler(repository, submitted.append)

    commands = scheduler.tick(datetime(2026, 8, 12, 6, 0, 29, tzinfo=UTC))

    assert [command.kind for command in commands] == ["run_once", "publish_once"]
    assert submitted == list(commands)
    assert all(
        command.scheduled_for == datetime(2026, 8, 12, 6, 0, tzinfo=UTC)
        for command in commands
    )


def test_tick_does_nothing_outside_configured_minute() -> None:
    # Поломка: polling запускает ближайший слот до его точной минуты.
    repository = ScheduleRepository(
        (
            _project(
                sources=(SourceSchedule(enabled=True, cron="0 9 * * *"),),
                routes=(RouteSchedule(True, True, ("09:00", "14:00", "19:00")),),
            ),
        )
    )
    submitted = []

    commands = ProjectScheduler(repository, submitted.append).tick(
        datetime(2026, 8, 12, 6, 1, tzinfo=UTC)
    )

    assert commands == ()
    assert submitted == []


def test_tick_evaluates_each_project_in_its_timezone() -> None:
    # Поломка: Moscow 09:00 сравнивается с UTC и пропускается.
    repository = ScheduleRepository(
        (
            _project(
                timezone="Europe/Moscow",
                sources=(SourceSchedule(True, "0 9 * * *"),),
            ),
        )
    )

    commands = ProjectScheduler(repository, lambda command: None).tick(
        datetime(2026, 8, 12, 6, 0, tzinfo=UTC)
    )

    assert [(command.project_id, command.kind) for command in commands] == [
        (41, "run_once")
    ]


def test_source_cron_supports_bootstrap_weekday_range() -> None:
    # Поломка: default `0 9 * * 1-5` никогда не due из-за literal-only matcher.
    repository = ScheduleRepository(
        (_project(sources=(SourceSchedule(True, "0 9 * * 1-5"),)),)
    )
    scheduler = ProjectScheduler(repository, lambda command: None)

    wednesday = scheduler.tick(datetime(2026, 8, 12, 6, 0, tzinfo=UTC))
    saturday = scheduler.tick(datetime(2026, 8, 15, 6, 0, tzinfo=UTC))

    assert [command.kind for command in wednesday] == ["run_once"]
    assert saturday == ()


def test_repeat_tick_in_same_minute_does_not_submit_claimed_slot_again() -> None:
    # Поломка: exact slot ключ включает секунды и repeat tick дублирует job.
    repository = ScheduleRepository(
        (_project(routes=(RouteSchedule(True, True, ("09:00", "14:00", "19:00")),)),)
    )
    submitted = []
    scheduler = ProjectScheduler(repository, submitted.append)

    first = scheduler.tick(datetime(2026, 8, 12, 6, 0, 0, tzinfo=UTC))
    second = scheduler.tick(datetime(2026, 8, 12, 6, 0, 30, tzinfo=UTC))

    assert [command.kind for command in first] == ["publish_once"]
    assert second == ()
    assert submitted == list(first)


def test_production_repository_passes_atomically_accepted_run_to_worker() -> None:
    # Поломка review: scheduler создаёт durable run, но worker пытается создать второй.
    class DurableScheduleRepository(ScheduleRepository):
        def accept(self, command) -> int:
            return 991

        def claim(self, command) -> bool:
            raise AssertionError("durable repository must use atomic accept")

    repository = DurableScheduleRepository(
        (_project(sources=(SourceSchedule(True, "0 9 * * *"),)),)
    )
    submitted = []

    commands = ProjectScheduler(repository, submitted.append).tick(
        datetime(2026, 8, 12, 6, tzinfo=UTC)
    )

    assert commands[0].operation_run_id == 991
    assert submitted == list(commands)


def test_disabled_sources_routes_and_autopublish_do_not_produce_commands() -> None:
    # Поломка: scheduler игнорирует enabled/autopublish и запускает отключённую работу.
    repository = ScheduleRepository(
        (
            _project(
                sources=(SourceSchedule(False, "0 9 * * *"),),
                routes=(
                    RouteSchedule(False, True, ("09:00", "14:00", "19:00")),
                    RouteSchedule(True, False, ("09:00", "14:00", "19:00")),
                ),
            ),
        )
    )

    commands = ProjectScheduler(repository, lambda command: None).tick(
        datetime(2026, 8, 12, 6, 0, tzinfo=UTC)
    )

    assert commands == ()


def test_runner_busy_does_not_turn_claimed_command_into_a_second_flow() -> None:
    # Поломка: scheduler перехватывает duplicate error и запускает job в обход runner.
    repository = ScheduleRepository(
        (_project(sources=(SourceSchedule(True, "0 9 * * *"),)),)
    )

    def busy(command) -> None:
        raise RuntimeError("operation_busy")

    scheduler = ProjectScheduler(repository, busy)

    try:
        scheduler.tick(datetime(2026, 8, 12, 6, 0, tzinfo=UTC))
    except RuntimeError as error:
        assert str(error) == "operation_busy"
    else:
        raise AssertionError("Scheduler must preserve runner duplicate semantics")


def test_scheduled_publish_uses_persisted_web_boundary_without_env_telegram_gate() -> None:
    # Поломка review: env Telegram решает доступность persisted route.
    from postify.web.services import WebApplication

    class Projects:
        def __init__(self) -> None:
            self.requested = []

        def get(self, project_id: int) -> object:
            self.requested.append(project_id)
            return object()

    class Operations:
        def __init__(self) -> None:
            self.submitted = []

        def submit(self, project_id, kind, operation) -> None:
            self.submitted.append((project_id, kind))

    application = object.__new__(WebApplication)
    application._projects = Projects()
    application._operations = Operations()
    application._telegram = None

    application._submit_scheduled(
        ScheduledCommand(
            41,
            "publish_once",
            datetime(2026, 8, 12, 6, tzinfo=UTC),
            operation_run_id=91,
        )
    )

    assert application._projects.requested == [41]
    assert application._operations.submitted == [(41, "publish_once")]
