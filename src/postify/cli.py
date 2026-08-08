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
    open_content_review,
    open_run_once,
    wait_for_database,
)
from postify.config import Settings
from postify.infrastructure.systemd import (
    RunOnceTimeoutError,
    SystemdCommandError,
    SystemdController,
)


app = typer.Typer(no_args_is_help=True)
content_app = typer.Typer(no_args_is_help=True)
app.add_typer(content_app, name="content")


def create_systemd_controller(settings: Settings) -> SystemdController:
    return SystemdController(
        command_name="systemctl",
        postgresql_unit=settings.postgresql_systemd_unit,
        clock=monotonic,
        sleeper=sleep,
        runner=lambda argv: subprocess.run(
            argv, check=False, capture_output=True, text=True
        ),
    )


def _fail(error: Exception) -> None:
    typer.echo(str(error), err=True)
    raise typer.Exit(code=1)


@app.command()
def run_once() -> None:
    """Импортировать кандидатов и применить отбор один раз."""
    try:
        settings = Settings()
        with open_run_once(settings) as job:
            result = job.execute()
    except SourceFetchError as error:
        _fail(error)
        return
    except ValidationError:
        _fail(RuntimeError("Некорректная конфигурация отбора"))
        return
    except (SQLAlchemyError, OSError, RuntimeError, ValueError):
        _fail(RuntimeError("Не удалось выполнить отбор кандидатов"))
        return

    typer.echo(
        f"Получено: {result.import_result.received}; новых: {result.import_result.created}; "
        f"дубликатов: {result.import_result.duplicates}; "
        f"проверено: {result.selection_result.examined}; "
        f"selected: {result.selection_result.selected}; "
        f"rejected: {result.selection_result.rejected}; "
        f"конфликты: {result.selection_result.conflicts}"
    )
    if getattr(result, "content_result", None) is not None:
        typer.echo(
            f"обработано: {result.content_result.claimed}; retry: {result.content_result.retry_scheduled}; ошибок: {result.content_result.failed}; пакетов: {result.content_result.packages_created}"
        )


def _content_error(action: str) -> None:
    _fail(RuntimeError(f"Не удалось {action} контентный пакет"))


@content_app.command("list")
def content_list() -> None:
    try:
        with open_content_review(Settings()) as review:
            for package in review.list_packages():
                typer.echo(f"{package.id}; {package.status}; {package.source_url}")
    except (ValidationError, OSError, SQLAlchemyError, ValueError):
        _content_error("показать")


@content_app.command("show")
def content_show(package_id: int) -> None:
    try:
        with open_content_review(Settings()) as review:
            p = review.show(package_id)
            typer.echo(
                "\n".join(
                    (
                        str(p.source_url),
                        str(p.context),
                        str(p.analysis),
                        str(p.post_text),
                        str(p.media_path),
                        str(p.media_source_type),
                        str(p.media_source_url),
                        *(
                            str(
                                getattr(
                                    h, "status", h[0] if isinstance(h, tuple) else h
                                )
                            )
                            for h in p.history
                        ),
                    )
                )
            )
    except (ValidationError, OSError, SQLAlchemyError, ValueError):
        _content_error("показать")


@content_app.command("approve")
def content_approve(package_id: int) -> None:
    try:
        with open_content_review(Settings()) as review:
            typer.echo(review.approve(package_id).status)
    except (ValidationError, OSError, SQLAlchemyError, ValueError):
        _content_error("одобрить")


@content_app.command("reject")
def content_reject(package_id: int) -> None:
    try:
        with open_content_review(Settings()) as review:
            typer.echo(review.reject(package_id).status)
    except (ValidationError, OSError, SQLAlchemyError, ValueError):
        _content_error("отклонить")


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
    except ValidationError:
        _fail(RuntimeError("Некорректная конфигурация"))
        return
    except (
        DatabaseUnavailableError,
        SystemdCommandError,
        SQLAlchemyError,
        RuntimeError,
    ) as error:
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
    except ValidationError:
        _fail(RuntimeError("Некорректная конфигурация"))
        return
    except (SystemdCommandError, SQLAlchemyError, OSError) as error:
        _fail(error)
        return

    typer.echo(
        f"PostgreSQL unit: {settings.postgresql_systemd_unit}; state: {postgresql_state}"
    )
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
    except ValidationError:
        _fail(RuntimeError("Некорректная конфигурация"))
        return
    except (RunOnceTimeoutError, SystemdCommandError) as error:
        _fail(error)
        return

    typer.echo("PostgreSQL и таймер Postify остановлены")
