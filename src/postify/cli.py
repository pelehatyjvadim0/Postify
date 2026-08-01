from __future__ import annotations

import subprocess
from time import monotonic, sleep

import typer
from alembic.util.exc import CommandError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from postify.application.ports.candidate_source import SourceFetchError
from postify.bootstrap import (
    DatabaseUnavailableError,
    candidate_count,
    database_is_ready,
    migrations_at_head,
    open_importer,
    wait_for_database,
)
from postify.config import Settings
from postify.infrastructure.systemd import (
    RunOnceTimeoutError,
    SystemdCommandError,
    SystemdController,
)


app = typer.Typer(no_args_is_help=True)


def create_systemd_controller(settings: Settings) -> SystemdController:
    return SystemdController(
        command_name="systemctl",
        postgresql_unit=settings.postgresql_systemd_unit,
        clock=monotonic,
        sleeper=sleep,
        runner=lambda argv: subprocess.run(argv, check=False, capture_output=True, text=True),
    )


def _fail(error: Exception) -> None:
    typer.echo(str(error), err=True)
    raise typer.Exit(code=1)


@app.command()
def run_once() -> None:
    """Импортировать кандидатов Hacker News один раз."""
    try:
        settings = Settings()
        with open_importer(settings) as importer:
            result = importer.execute()
    except (ValidationError, SourceFetchError, SQLAlchemyError, OSError) as error:
        _fail(error)
        return

    typer.echo(
        f"Получено: {result.received}; новых: {result.created}; дубликатов: {result.duplicates}"
    )


@app.command()
def start() -> None:
    """Запустить PostgreSQL и планировщик, когда БД готова."""
    try:
        settings = Settings()
        systemd = create_systemd_controller(settings)
        systemd.start_postgresql()
        wait_for_database(settings)
        try:
            migrations_ready = migrations_at_head(settings)
        except (CommandError, OSError):
            _fail(RuntimeError("Не удалось проверить миграции"))
            return
        if not migrations_ready:
            raise RuntimeError("Миграции БД не находятся на Alembic head")
        systemd.enable_and_start_timer()
    except (ValidationError, DatabaseUnavailableError, SystemdCommandError, SQLAlchemyError, RuntimeError) as error:
        _fail(error)
        return

    typer.echo("Таймер Postify запущен")


@app.command()
def status() -> None:
    """Показать текущее состояние PostgreSQL и планировщика."""
    try:
        settings = Settings()
        systemd = create_systemd_controller(settings)
        postgresql_state = systemd.active_state(settings.postgresql_systemd_unit)
        timer_state = systemd.active_state("postify-run-once.timer")
        run_once_state = systemd.active_state("postify-run-once.service")
        timer = systemd.timer_properties()
        ready = database_is_ready(settings)
        count = candidate_count(settings) if ready else None
    except (ValidationError, SystemdCommandError, SQLAlchemyError, OSError) as error:
        _fail(error)
        return

    typer.echo(f"PostgreSQL unit: {settings.postgresql_systemd_unit}; state: {postgresql_state}")
    typer.echo("БД: доступна; кандидатов: " + str(count) if ready else "БД: недоступна")
    typer.echo(
        "Таймер: "
        f"{timer_state}; последнее: {timer.get('LastTriggerUSec', 'неизвестно')}; "
        f"следующее: {timer.get('NextElapseUSecRealtime', 'неизвестно')}"
    )
    typer.echo(f"run-once: {run_once_state}")


@app.command()
def stop() -> None:
    """Остановить планировщик и PostgreSQL после завершения run-once."""
    try:
        settings = Settings()
        systemd = create_systemd_controller(settings)
        systemd.disable_and_stop_timer()
        systemd.wait_for_run_once(
            timeout=settings.run_once_wait_timeout_seconds,
            poll_interval=0.1,
        )
        systemd.stop_postgresql()
    except (ValidationError, RunOnceTimeoutError, SystemdCommandError) as error:
        _fail(error)
        return

    typer.echo("PostgreSQL и таймер Postify остановлены")
