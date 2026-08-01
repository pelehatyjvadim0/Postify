from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace

from typer.testing import CliRunner

from postify.application.ingestion.import_candidates import ImportResult
from postify.application.ports.candidate_source import SourceFetchError


runner = CliRunner()


@dataclass
class FakeImporter:
    result: ImportResult | None = None
    error: Exception | None = None

    def execute(self) -> ImportResult:
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@contextmanager
def importer_context(importer: FakeImporter):
    yield importer


class FakeSystemd:
    def __init__(self, events: list[str], *, run_once_error: Exception | None = None) -> None:
        self.events = events
        self.run_once_error = run_once_error

    def start_postgresql(self) -> None:
        self.events.append("postgresql:start")

    def stop_postgresql(self) -> None:
        self.events.append("postgresql:stop")

    def enable_and_start_timer(self) -> None:
        self.events.append("timer:enable-start")

    def disable_and_stop_timer(self) -> None:
        self.events.append("timer:disable-stop")

    def wait_for_run_once(self, *, timeout: float, poll_interval: float) -> str:
        self.events.append(f"run-once:wait:{timeout}:{poll_interval}")
        if self.run_once_error is not None:
            raise self.run_once_error
        return "inactive"

    def active_state(self, unit: str) -> str:
        self.events.append(f"state:{unit}")
        return {
            "postgresql-custom.service": "active",
            "postify-run-once.timer": "active",
            "postify-run-once.service": "inactive",
        }[unit]

    def timer_properties(self) -> dict[str, str]:
        return {"LastTriggerUSec": "сегодня", "NextElapseUSecRealtime": "завтра"}


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        postgresql_systemd_unit="postgresql-custom.service",
        database_readiness_timeout_seconds=5.0,
        run_once_wait_timeout_seconds=7.0,
    )


def test_run_once_prints_import_result_from_real_typer_command(monkeypatch) -> None:
    # Break caught: a CLI command that does not expose all three import counters.
    from postify import cli

    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(
        cli,
        "open_importer",
        lambda configured_settings: importer_context(FakeImporter(ImportResult(3, 2, 1))),
    )

    result = runner.invoke(cli.app, ["run-once"])

    assert result.exit_code == 0
    assert result.output == "Получено: 3; новых: 2; дубликатов: 1\n"


def test_run_once_reports_source_error_without_traceback(monkeypatch) -> None:
    # Break caught: leaking a traceback or returning success when the source is unavailable.
    from postify import cli

    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(
        cli,
        "open_importer",
        lambda configured_settings: importer_context(FakeImporter(error=SourceFetchError("источник недоступен"))),
    )

    result = runner.invoke(cli.app, ["run-once"])

    assert result.exit_code != 0
    assert "источник недоступен" in result.output
    assert "Traceback" not in result.output


def test_start_does_not_enable_timer_when_database_is_unavailable(monkeypatch) -> None:
    # Break caught: enabling the timer before the PostgreSQL readiness gate passes.
    from postify import cli

    events: list[str] = []
    systemd = FakeSystemd(events)
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(cli, "create_systemd_controller", lambda configured_settings: systemd)
    monkeypatch.setattr(
        cli,
        "wait_for_database",
        lambda configured_settings: (_ for _ in ()).throw(RuntimeError("БД недоступна")),
    )

    result = runner.invoke(cli.app, ["start"])

    assert result.exit_code != 0
    assert "БД недоступна" in result.output
    assert events == ["postgresql:start"]


def test_start_enables_timer_only_after_database_and_migrations(monkeypatch) -> None:
    # Break caught: a timer enabled before readiness or migration checks complete.
    from postify import cli

    events: list[str] = []
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(cli, "create_systemd_controller", lambda configured_settings: FakeSystemd(events))
    monkeypatch.setattr(cli, "wait_for_database", lambda configured_settings: events.append("database:ready"))
    monkeypatch.setattr(
        cli,
        "migrations_at_head",
        lambda configured_settings: events.append("migrations:head") or True,
    )

    result = runner.invoke(cli.app, ["start"])

    assert result.exit_code == 0
    assert "Таймер Postify запущен" in result.output
    assert events == ["postgresql:start", "database:ready", "migrations:head", "timer:enable-start"]


def test_start_does_not_enable_timer_when_migrations_are_behind(monkeypatch) -> None:
    # Break caught: scheduling imports against a database whose schema is not at Alembic head.
    from postify import cli

    events: list[str] = []
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(cli, "create_systemd_controller", lambda configured_settings: FakeSystemd(events))
    monkeypatch.setattr(cli, "wait_for_database", lambda configured_settings: events.append("database:ready"))
    monkeypatch.setattr(cli, "migrations_at_head", lambda configured_settings: False)

    result = runner.invoke(cli.app, ["start"])

    assert result.exit_code != 0
    assert "Миграции" in result.output
    assert events == ["postgresql:start", "database:ready"]


def test_start_normalizes_alembic_check_error_without_enabling_timer(monkeypatch) -> None:
    # Break caught: a traceback after PostgreSQL starts when Alembic cannot find its scripts.
    from alembic.util.exc import CommandError
    from postify import cli

    events: list[str] = []
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(cli, "create_systemd_controller", lambda configured_settings: FakeSystemd(events))
    monkeypatch.setattr(cli, "wait_for_database", lambda configured_settings: events.append("database:ready"))
    monkeypatch.setattr(
        cli,
        "migrations_at_head",
        lambda configured_settings: (_ for _ in ()).throw(CommandError("No 'script_location' key")),
    )

    result = runner.invoke(cli.app, ["start"])

    assert result.exit_code != 0
    assert "Не удалось проверить миграции" in result.output
    assert "Traceback" not in result.output
    assert events == ["postgresql:start", "database:ready"]


def test_status_reports_real_boundary_data_without_inventing_queue_or_errors(monkeypatch) -> None:
    # Break caught: status omits a required state or invents future queue/error information.
    from postify import cli

    events: list[str] = []
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(cli, "create_systemd_controller", lambda configured_settings: FakeSystemd(events))
    monkeypatch.setattr(cli, "database_is_ready", lambda configured_settings: True)
    monkeypatch.setattr(cli, "candidate_count", lambda configured_settings: 4)

    result = runner.invoke(cli.app, ["status"])

    assert result.exit_code == 0
    assert "PostgreSQL unit: postgresql-custom.service; state: active" in result.output
    assert "БД: доступна; кандидатов: 4" in result.output
    assert "Таймер: active; последнее: сегодня; следующее: завтра" in result.output
    assert "run-once: inactive" in result.output
    assert "очеред" not in result.output.lower()
    assert "ошибк" not in result.output.lower()
    assert events == [
        "state:postgresql-custom.service",
        "state:postify-run-once.timer",
        "state:postify-run-once.service",
    ]


def test_stop_keeps_postgresql_running_when_run_once_wait_times_out(monkeypatch) -> None:
    # Break caught: stopping PostgreSQL while the active one-off import may still write to it.
    from postify import cli
    from postify.infrastructure.systemd import RunOnceTimeoutError

    events: list[str] = []
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(
        cli,
        "create_systemd_controller",
        lambda configured_settings: FakeSystemd(events, run_once_error=RunOnceTimeoutError("долгое выполнение")),
    )

    result = runner.invoke(cli.app, ["stop"])

    assert result.exit_code != 0
    assert "долгое выполнение" in result.output
    assert events == ["timer:disable-stop", "run-once:wait:7.0:0.1"]


def test_stop_stops_postgresql_after_run_once_finishes(monkeypatch) -> None:
    # Break caught: leaving PostgreSQL running after the timer and active import have stopped.
    from postify import cli

    events: list[str] = []
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(cli, "create_systemd_controller", lambda configured_settings: FakeSystemd(events))

    result = runner.invoke(cli.app, ["stop"])

    assert result.exit_code == 0
    assert "PostgreSQL и таймер Postify остановлены" in result.output
    assert events == ["timer:disable-stop", "run-once:wait:7.0:0.1", "postgresql:stop"]
