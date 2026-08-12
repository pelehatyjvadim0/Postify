from __future__ import annotations

import subprocess
from datetime import datetime
from time import monotonic, sleep

import typer
import uvicorn
from alembic.util.exc import CommandError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from postify.application.ports.candidate_source import SourceFetchError
from postify.bootstrap import (
    DatabaseUnavailableError,
    candidate_count,
    database_is_ready,
    migrations_at_head,
    open_operational_status,
    open_content_review,
    open_publish_once,
    open_run_once,
    wait_for_database,
)
from postify.application.observability.show_status import RuntimeSnapshot
from postify.config import Settings, TelegramSettings
from postify.infrastructure.systemd import (
    RunOnceTimeoutError,
    SystemdCommandError,
    SystemdController,
)


app = typer.Typer(no_args_is_help=True)
content_app = typer.Typer(no_args_is_help=True)
app.add_typer(content_app, name="content")


@app.command()
def ui(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000, min=1, max=65535),
) -> None:
    """Запустить локальный HTTP-интерфейс Postify."""
    from postify.web.app import create_app

    uvicorn.run(create_app(), host=host, port=port)


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


@app.command("publish-once")
def publish_once() -> None:
    """Опубликовать один подтверждённый пакет в Telegram."""
    try:
        settings = Settings()
        telegram = TelegramSettings()
        with open_publish_once(settings, telegram) as action:
            result = action.execute()
    except ValidationError:
        _fail(RuntimeError("Некорректная конфигурация Telegram"))
        return
    except (SQLAlchemyError, OSError, RuntimeError, ValueError):
        _fail(RuntimeError("Не удалось выполнить Telegram-доставку"))
        return
    if result.outcome == "empty":
        typer.echo("Слот пуст")
    elif result.outcome == "published":
        typer.echo(
            f"Опубликован пакет {result.package_id}; message_id={result.message_id}"
        )
    elif result.outcome == "cleanup_completed":
        typer.echo(f"Cleanup завершён для пакета {result.package_id}")
    elif result.outcome == "cleanup_pending":
        typer.echo(f"Cleanup ожидает повтора для пакета {result.package_id}")
    else:
        typer.echo(f"Исход доставки пакета {result.package_id}: {result.outcome}")


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
        systemd.enable_and_start_publish_timer()
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


def _probe_runtime(systemd, settings) -> RuntimeSnapshot:
    failed: list[str] = []

    def state(unit: str) -> str:
        try:
            return systemd.active_state(unit)
        except (Exception,):
            failed.append(unit)
            return "unknown"

    def timer(properties, unit: str) -> tuple[str | None, str | None]:
        try:
            values = properties()
            return values.get("LastTriggerUSec"), values.get("NextElapseUSecRealtime")
        except (Exception,):
            if unit not in failed:
                failed.append(unit)
            return None, None

    postgresql = state(settings.postgresql_systemd_unit)
    import_timer = state("postify-run-once.timer")
    publish_timer = state("postify-publish-once.timer")
    run_service = state("postify-run-once.service")
    publish_service = state("postify-publish-once.service")
    import_last, import_next = timer(systemd.timer_properties, "postify-run-once.timer")
    publish_last, publish_next = timer(
        systemd.publish_timer_properties, "postify-publish-once.timer"
    )
    return RuntimeSnapshot(
        postgresql=postgresql,
        import_timer=import_timer,
        publish_timer=publish_timer,
        run_once_service_active=run_service == "active",
        publish_once_service_active=publish_service == "active",
        import_timer_last=import_last,
        import_timer_next=import_next,
        publish_timer_last=publish_last,
        publish_timer_next=publish_next,
        systemd_failures=tuple(failed),
        probe_failed_units=tuple(failed),
    )


def _local_time(value, timezone: str) -> str:
    if value is None:
        return "—"
    from zoneinfo import ZoneInfo

    if isinstance(value, datetime):
        return value.astimezone(ZoneInfo(timezone)).isoformat(timespec="seconds")
    return str(value)


def _render_runtime(runtime: RuntimeSnapshot, *, migrations: str) -> tuple[str, ...]:
    return (
        "Система",
        f"  PostgreSQL: доступна; migrations={migrations}",
        f"  import timer: {runtime.import_timer}; последнее={runtime.import_timer_last or '—'}; следующее={runtime.import_timer_next or '—'}",
        f"  publish timer: {runtime.publish_timer}; последнее={runtime.publish_timer_last or '—'}; следующее={runtime.publish_timer_next or '—'}",
    )


def _render_status(report) -> tuple[str, ...]:
    lines = (
        list(_render_runtime(report.runtime, migrations="head"))
        if hasattr(report, "runtime")
        else ["Система", "  PostgreSQL: доступна; migrations=head"]
    )

    # runtime добавляется командой, однако renderer остаётся чистой функцией для report.
    def groups(values, expected: tuple[str, ...] = ()) -> str:
        by_code = {item.code: item.count for item in values}
        fixed = [f"{code}={by_code.pop(code, 0)}" for code in expected]
        unknown = [f"{code}={count}" for code, count in by_code.items()]
        return "; ".join((*fixed, *unknown))

    lines += [
        "Сущности",
        f"  candidates: total={report.candidate_total}; undecided={report.candidate_undecided}; {groups(report.candidate_decisions, ('selected', 'rejected'))}",
        f"  rejection reasons: {groups(getattr(report, 'rejection_reasons', ()), ('advertising', 'out_of_scope', 'hiring', 'technical_without_use'))}",
        f"  content attempts: {groups(report.content_attempts)}",
        f"  packages: {groups(report.packages)}",
        f"  delivery: {groups(report.delivery)}",
        "Последние пакеты (до 10)",
    ]
    lines += [
        f"  package={item.package_id}; status={item.status}; created_at={_local_time(item.created_at, report.timezone)}"
        for item in report.latest_packages
    ] or ["  —"]
    lines.append("Доставка (последние 10 попыток)")
    lines += [
        f"  package={item.package_id}; attempt={item.attempt_no}; outcome={item.outcome}; finished_at={_local_time(item.finished_at, report.timezone)}; message_id={item.message_id if item.message_id is not None else '—'}"
        for item in report.latest_delivery_attempts
    ] or ["  —"]
    lines += [
        f"План на {report.day.isoformat()} ({report.timezone})",
        f"  цель={report.daily_target}; опубликовано={report.published_today}; готово={report.delivery_ready}; дефицит={report.deficit}",
        f"  причины: {', '.join(report.deficit_reasons)}",
        "Последние запуски (до 10)",
    ]
    lines += [
        f"  run={item.run_id}; operation={item.operation}; status={item.status}; outcome={item.outcome or '—'}; failure_code={item.failure_code or '—'}; started_at={_local_time(item.started_at, report.timezone)}; finished_at={_local_time(item.finished_at, report.timezone)}"
        for item in report.latest_operation_runs
    ] or ["  —"]
    lines.append("Проблемы")
    lines += [
        f"  {item.severity.upper()} {item.code}: count={item.count}"
        + (f"; ids={','.join(str(value) for value in item.ids)}" if item.ids else "")
        for item in report.signals
    ] or ["  Проблем нет"]
    return tuple(lines)


@app.command()
def status() -> None:
    """Показать согласованное эксплуатационное состояние Postify."""
    try:
        settings = Settings()
        if not hasattr(settings, "postify_timezone"):
            systemd = create_systemd_controller(settings)
            postgresql_state = systemd.active_state(settings.postgresql_systemd_unit)
            timer_state = systemd.active_state("postify-run-once.timer")
            publish_timer_state = systemd.active_state("postify-publish-once.timer")
            run_once_state = systemd.active_state("postify-run-once.service")
            timer = systemd.timer_properties()
            publish_timer = systemd.publish_timer_properties()
            ready = database_is_ready(settings)
            count = candidate_count(settings) if ready else None
            typer.echo(
                f"PostgreSQL unit: {settings.postgresql_systemd_unit}; state: {postgresql_state}"
            )
            typer.echo(
                "БД: доступна; кандидатов: " + str(count) if ready else "БД: недоступна"
            )
            typer.echo(
                f"Таймер: {timer_state}; последнее: {timer.get('LastTriggerUSec', 'неизвестно')}; следующее: {timer.get('NextElapseUSecRealtime', 'неизвестно')}"
            )
            typer.echo(f"run-once: {run_once_state}")
            typer.echo(
                f"Telegram-таймер: {publish_timer_state}; последнее: {publish_timer.get('LastTriggerUSec', 'неизвестно')}; следующее: {publish_timer.get('NextElapseUSecRealtime', 'неизвестно')}"
            )
            return
        runtime = _probe_runtime(create_systemd_controller(settings), settings)
    except ValidationError:
        _fail(RuntimeError("Некорректная конфигурация"))
        return
    lines = list(_render_runtime(runtime, migrations="head"))
    try:
        if not database_is_ready(settings):
            raise RuntimeError("database_unavailable")
        if not migrations_at_head(settings):
            raise RuntimeError("migration_not_at_head")
        with open_operational_status(settings) as action:
            report = action.execute(runtime)
        lines = list(_render_status(report))
        # _render_status receives only report in tests; retain probed facts for real CLI.
        lines[:2] = _render_runtime(runtime, migrations="head")
    except (SQLAlchemyError, OSError, RuntimeError, CommandError) as error:
        code = (
            str(error)
            if str(error) in {"database_unavailable", "migration_not_at_head"}
            else "database_unavailable"
        )
        lines = list(
            _render_runtime(
                runtime,
                migrations="head" if code != "migration_not_at_head" else "not_head",
            )
        )
        lines += [
            "Проблемы",
            f"  CRITICAL {code}: count=1",
            "Не удалось получить состояние Postify",
        ]
        typer.echo("\n".join(lines))
        raise typer.Exit(code=1)
    typer.echo("\n".join(lines))


@app.command()
def stop() -> None:
    """Остановить планировщик и PostgreSQL после завершения run-once."""
    try:
        settings = Settings()
        systemd = create_systemd_controller(settings)
        systemd.disable_and_stop_timer()
        systemd.disable_and_stop_publish_timer()
        systemd.wait_for_run_once(
            timeout=settings.run_once_wait_timeout_seconds,
            poll_interval=0.1,
        )
        systemd.wait_for_publish_once(
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
