from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from postify.application.ingestion.import_candidates import ImportResult
from postify.application.ports.candidate_source import SourceFetchError


runner = CliRunner()


@dataclass(frozen=True)
class FakeSelectionResult:
    examined: int
    selected: int
    rejected: int
    conflicts: int


@dataclass(frozen=True)
class FakeRunOnceResult:
    import_result: ImportResult
    selection_result: FakeSelectionResult


@dataclass
class FakeRunOnce:
    result: FakeRunOnceResult | None = None
    error: Exception | None = None

    def execute(self) -> FakeRunOnceResult:
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@contextmanager
def run_once_context(run_once: FakeRunOnce):
    yield run_once


class FakeSystemd:
    def __init__(self, events: list[str], *, run_once_error: Exception | None = None, publish_error: Exception | None = None) -> None:
        self.events = events
        self.run_once_error = run_once_error
        self.publish_error = publish_error

    def start_postgresql(self) -> None:
        self.events.append("postgresql:start")

    def stop_postgresql(self) -> None:
        self.events.append("postgresql:stop")

    def enable_and_start_timer(self) -> None:
        self.events.append("timer:enable-start")

    def enable_and_start_publish_timer(self) -> None:
        self.events.append("publish-timer:enable-start")

    def disable_and_stop_timer(self) -> None:
        self.events.append("timer:disable-stop")

    def disable_and_stop_publish_timer(self) -> None:
        self.events.append("publish-timer:disable-stop")

    def wait_for_run_once(self, *, timeout: float, poll_interval: float) -> str:
        self.events.append(f"run-once:wait:{timeout}:{poll_interval}")
        if self.run_once_error is not None:
            raise self.run_once_error
        return "inactive"

    def wait_for_publish_once(self, *, timeout: float, poll_interval: float) -> str:
        self.events.append(f"publish-once:wait:{timeout}:{poll_interval}")
        if self.publish_error is not None:
            raise self.publish_error
        return "inactive"

    def active_state(self, unit: str) -> str:
        self.events.append(f"state:{unit}")
        return {
            "postgresql-custom.service": "active",
            "postify-run-once.timer": "active",
            "postify-publish-once.timer": "active",
            "postify-run-once.service": "inactive",
        }[unit]

    def timer_properties(self) -> dict[str, str]:
        return {"LastTriggerUSec": "сегодня", "NextElapseUSecRealtime": "завтра"}

    def publish_timer_properties(self) -> dict[str, str]:
        return {"LastTriggerUSec": "сегодня", "NextElapseUSecRealtime": "завтра"}


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        postgresql_systemd_unit="postgresql-custom.service",
        database_readiness_timeout_seconds=5.0,
        run_once_wait_timeout_seconds=7.0,
    )


def test_run_once_prints_import_and_selection_result_from_real_typer_command(monkeypatch) -> None:
    # Поломка: CLI не показывает все счётчики общего import → selection сценария.
    from postify import cli

    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(
        cli,
        "open_run_once",
        lambda configured_settings: run_once_context(
            FakeRunOnce(
                FakeRunOnceResult(
                    import_result=ImportResult(3, 2, 1),
                    selection_result=FakeSelectionResult(4, 3, 1, 0),
                )
            )
        ),
    )

    result = runner.invoke(cli.app, ["run-once"])

    assert result.exit_code == 0
    assert result.output == (
        "Получено: 3; новых: 2; дубликатов: 1; "
        "проверено: 4; selected: 3; rejected: 1; конфликты: 0\n"
    )


def test_open_run_once_yields_recorded_action_and_preserves_execute_result(monkeypatch) -> None:
    # Поломка: bootstrap обходит running→succeeded journal или меняет result RunOnce.
    from postify import bootstrap
    from postify.application.observability.record_operation import RecordedAction
    from postify.infrastructure.repositories import sqlalchemy_observability

    events: list[tuple[str, object]] = []
    expected = object()

    class Journal:
        def __init__(self, factory) -> None:
            assert factory is resources.session_factory

        def start(self, operation, *, now, mode, actor):
            assert (mode, actor) == ("automatic", "scheduler")
            events.append(("start", operation.value))
            return 71

        def succeed(self, run_id, *, outcome, now, **metadata):
            assert run_id == 71
            assert metadata == {
                "codex_model": None,
                "codex_reasoning_effort": None,
                "materials_taken": 0,
                "packages_created": 0,
            }
            events.append(("succeed", outcome))

        def fail(self, run_id, *, failure_code, now):
            events.append(("fail", failure_code))

    class Underlying:
        def execute(self):
            events.append(("action", "run_once"))
            return expected

    resources = SimpleNamespace(
        source=object(),
        session_factory=object(),
        client=object(),
        url_policy=object(),
    )

    @contextmanager
    def opened_resources(settings, *, transport=None):
        yield resources

    monkeypatch.setattr(bootstrap, "_open_import_resources", opened_resources)
    monkeypatch.setattr(bootstrap, "selection_profile_from_settings", lambda configured: object())
    monkeypatch.setattr(bootstrap, "ImportCandidates", lambda *args: object())
    monkeypatch.setattr(bootstrap, "SelectCandidates", lambda *args: object())
    monkeypatch.setattr(bootstrap, "RunOnce", lambda *args: Underlying())
    monkeypatch.setattr(bootstrap, "_content_processor", lambda *args: None)
    monkeypatch.setattr(sqlalchemy_observability, "SqlAlchemyOperationRunRepository", Journal)

    with bootstrap.open_run_once(SimpleNamespace()) as action:
        assert isinstance(action, RecordedAction)
        result = action.execute()

    assert result is expected
    assert events == [
        ("start", "run_once"),
        ("action", "run_once"),
        ("succeed", "completed"),
    ]


def test_run_once_reports_source_error_without_traceback(monkeypatch) -> None:
    # Break caught: leaking a traceback or returning success when the source is unavailable.
    from postify import cli

    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(
        cli,
        "open_run_once",
        lambda configured_settings: run_once_context(
            FakeRunOnce(error=SourceFetchError("источник недоступен"))
        ),
    )

    result = runner.invoke(cli.app, ["run-once"])

    assert result.exit_code != 0
    assert "источник недоступен" in result.output
    assert "Traceback" not in result.output


def test_run_once_reports_selection_sql_error_without_sensitive_data(monkeypatch) -> None:
    # Поломка: ошибка SQL возвращает код 0 либо раскрывает кандидата/raw_payload.
    from sqlalchemy.exc import SQLAlchemyError
    from postify import cli

    leaked_error = SQLAlchemyError(
        "insert failed; raw_payload={'title': 'Секретный кандидат', 'points': 9000}"
    )
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(
        cli,
        "open_run_once",
        lambda configured_settings: run_once_context(FakeRunOnce(error=leaked_error)),
    )

    result = runner.invoke(cli.app, ["run-once"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "raw_payload" not in result.output
    assert "Секретный кандидат" not in result.output
    assert "points" not in result.output


def test_run_once_does_not_hide_selection_contract_error_or_leak_candidate(monkeypatch) -> None:
    # Поломка (mutation 13): selection ValueError скрывается с кодом 0 или раскрывает данные.
    from postify import cli

    leaked_error = ValueError(
        "unknown candidate 999; raw_payload={'title': 'Закрытый материал'}"
    )
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(
        cli,
        "open_run_once",
        lambda configured_settings: run_once_context(FakeRunOnce(error=leaked_error)),
    )

    result = runner.invoke(cli.app, ["run-once"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "raw_payload" not in result.output
    assert "Закрытый материал" not in result.output


def test_run_once_normalizes_runtime_error_from_execution_and_cleanup(monkeypatch) -> None:
    # Поломка final fix: pipeline RuntimeError выходит из CLI без operator message.
    from postify import cli

    leaked_text = (
        "pipeline failed at https://sentinel.invalid/private "
        "in /srv/postify/SENTINEL-PATH with SENTINEL-SECRET"
    )
    successful_result = FakeRunOnceResult(
        import_result=ImportResult(3, 2, 1),
        selection_result=FakeSelectionResult(4, 3, 1, 0),
    )

    @contextmanager
    def failing_context(phase: str):
        if phase == "execute":
            yield FakeRunOnce(error=RuntimeError(leaked_text))
            return
        yield FakeRunOnce(result=successful_result)
        raise RuntimeError(leaked_text)

    monkeypatch.setattr(cli, "Settings", settings)
    results = []
    for phase in ("execute", "cleanup"):
        monkeypatch.setattr(
            cli,
            "open_run_once",
            lambda configured_settings, phase=phase: failing_context(phase),
        )

        results.append(runner.invoke(cli.app, ["run-once"]))

    for result in results:
        assert result.exit_code != 0
        assert result.output == "Не удалось выполнить отбор кандидатов\n"
        assert not isinstance(result.exception, RuntimeError)
        assert "Traceback" not in result.output
        assert "sentinel.invalid" not in result.output
        assert "SENTINEL-PATH" not in result.output
        assert "SENTINEL-SECRET" not in result.output
        assert leaked_text not in result.output
        assert "Получено:" not in result.output


@pytest.mark.parametrize("command", ["run-once", "start", "status", "stop"])
def test_command_reports_invalid_profile_without_exposing_data_or_calling_boundaries(
    monkeypatch,
    command: str,
) -> None:
    # Поломка Important: lifecycle-команда печатает field/value ValidationError либо идёт дальше.
    from pydantic import BaseModel, Field
    from postify import cli

    class InvalidProfile(BaseModel):
        advertising_terms: str = Field(min_length=100)

    def invalid_settings():
        return InvalidProfile(advertising_terms="секретный-рекламный-словарь")

    boundary_calls: list[str] = []

    def forbidden_boundary(*args: object, **kwargs: object):
        boundary_calls.append("called")
        raise AssertionError("Граница не должна вызываться после ошибки Settings")

    monkeypatch.setattr(cli, "Settings", invalid_settings)
    for boundary_name in (
        "open_run_once",
        "create_systemd_controller",
        "wait_for_database",
        "migrations_at_head",
        "database_is_ready",
        "candidate_count",
    ):
        monkeypatch.setattr(cli, boundary_name, forbidden_boundary)

    result = runner.invoke(cli.app, [command])

    assert result.exit_code != 0
    assert boundary_calls == []
    assert "Traceback" not in result.output
    assert "секретный-рекламный-словарь" not in result.output
    assert "секретный" not in result.output
    assert "словарь" not in result.output
    assert "advertising_terms" not in result.output


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
    assert events == ["postgresql:start", "database:ready", "migrations:head", "timer:enable-start", "publish-timer:enable-start"]


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
    assert "Telegram-таймер: active; последнее: сегодня; следующее: завтра" in result.output
    assert "очеред" not in result.output.lower()
    assert "ошибк" not in result.output.lower()
    assert events == [
        "state:postgresql-custom.service",
        "state:postify-run-once.timer",
        "state:postify-publish-once.timer",
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
    assert events == ["timer:disable-stop", "publish-timer:disable-stop", "run-once:wait:7.0:0.1"]


def test_stop_stops_postgresql_after_run_once_finishes(monkeypatch) -> None:
    # Break caught: leaving PostgreSQL running after the timer and active import have stopped.
    from postify import cli

    events: list[str] = []
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(cli, "create_systemd_controller", lambda configured_settings: FakeSystemd(events))

    result = runner.invoke(cli.app, ["stop"])

    assert result.exit_code == 0
    assert "PostgreSQL и таймер Postify остановлены" in result.output
    assert events == ["timer:disable-stop", "publish-timer:disable-stop", "run-once:wait:7.0:0.1", "publish-once:wait:7.0:0.1", "postgresql:stop"]


def test_stop_keeps_postgresql_running_when_publish_wait_times_out(monkeypatch) -> None:
    # Поломка: publish confirmation ещё active, но PostgreSQL уже остановлен.
    from postify import cli
    from postify.infrastructure.systemd import RunOnceTimeoutError

    events: list[str] = []
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(
        cli,
        "create_systemd_controller",
        lambda configured_settings: FakeSystemd(
            events, publish_error=RunOnceTimeoutError("postify-publish-once.service")
        ),
    )

    result = runner.invoke(cli.app, ["stop"])

    assert result.exit_code != 0
    assert "postify-publish-once.service" in result.output
    assert "Traceback" not in result.output
    assert events == [
        "timer:disable-stop",
        "publish-timer:disable-stop",
        "run-once:wait:7.0:0.1",
        "publish-once:wait:7.0:0.1",
    ]


@dataclass
class FakeContentReview:
    package: SimpleNamespace

    def list_packages(self):
        return (self.package,)

    def show(self, package_id: int):
        assert package_id == self.package.id
        return self.package

    def approve(self, package_id: int):
        assert package_id == self.package.id
        self.package.status = "approved"
        return self.package

    def reject(self, package_id: int):
        assert package_id == self.package.id
        self.package.status = "rejected"
        return self.package


def _content_package() -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        source_url="https://source.test/article-7",
        context="ARTICLE-BODY-MARKER полный извлечённый контекст",
        analysis="Практический анализ темы",
        post_text="Готовый русский текст поста",
        media_path="/var/lib/postify/media/7.jpg",
        media_source_type="og",
        media_source_url="https://cdn.test/7.jpg",
        status="awaiting_review",
        history=(
            SimpleNamespace(status="not_started", reason="claimed"),
            SimpleNamespace(status="processing", reason="analysis_started"),
            SimpleNamespace(status="awaiting_review", reason="media_stored"),
        ),
    )


def test_run_once_prints_content_counters_from_real_typer_command(monkeypatch) -> None:
    # Поломка: run-once создаёт пакеты, но CLI показывает только Wave 2.
    from postify import cli

    result_value = SimpleNamespace(
        import_result=ImportResult(3, 2, 1),
        selection_result=FakeSelectionResult(4, 3, 1, 0),
        content_result=SimpleNamespace(
            claimed=12,
            retry_scheduled=1,
            failed=2,
            packages_created=3,
        ),
    )
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(
        cli,
        "open_run_once",
        lambda configured_settings: run_once_context(FakeRunOnce(result=result_value)),
    )

    result = runner.invoke(cli.app, ["run-once"])

    assert result.exit_code == 0
    assert "обработано: 12" in result.output
    assert "retry: 1" in result.output
    assert "ошибок: 2" in result.output
    assert "пакетов: 3" in result.output


def test_content_list_prints_id_status_and_source_without_full_body(monkeypatch) -> None:
    # Поломка: content list не даёт оператору ID/status/source или печатае весь body.
    from postify import cli

    package = _content_package()
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(
        cli,
        "open_content_review",
        lambda configured_settings: run_once_context(FakeContentReview(package)),
        raising=False,
    )

    result = runner.invoke(cli.app, ["content", "list"])

    assert result.exit_code == 0
    assert "7" in result.output
    assert "awaiting_review" in result.output
    assert "https://source.test/article-7" in result.output
    assert "ARTICLE-BODY-MARKER" not in result.output


def test_content_show_prints_complete_auditable_package(monkeypatch) -> None:
    # Поломка (gate 7): show скрывает URL/context/analysis/media source/history.
    from postify import cli

    package = _content_package()
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(
        cli,
        "open_content_review",
        lambda configured_settings: run_once_context(FakeContentReview(package)),
        raising=False,
    )

    result = runner.invoke(cli.app, ["content", "show", "7"])

    assert result.exit_code == 0
    for visible in (
        "https://source.test/article-7",
        "ARTICLE-BODY-MARKER полный извлечённый контекст",
        "Практический анализ темы",
        "Готовый русский текст поста",
        "/var/lib/postify/media/7.jpg",
        "og",
        "https://cdn.test/7.jpg",
        "not_started",
        "processing",
        "awaiting_review",
    ):
        assert visible in result.output


@pytest.mark.parametrize(
    ("command", "expected_status"),
    [("approve", "approved"), ("reject", "rejected")],
)
def test_content_review_commands_report_final_status(
    monkeypatch, command: str, expected_status: str
) -> None:
    # Поломка (gate 6): CLI вызывает неверный review-action или сообщает успех без итогового статуса.
    from postify import cli

    package = _content_package()
    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(
        cli,
        "open_content_review",
        lambda configured_settings: run_once_context(FakeContentReview(package)),
        raising=False,
    )

    result = runner.invoke(cli.app, ["content", command, "7"])

    assert result.exit_code == 0
    assert expected_status in result.output
    assert package.status == expected_status


def test_content_cli_normalizes_error_without_secret_or_traceback(monkeypatch) -> None:
    # Поломка (gate 10): CLI раскрывает SQL/URL/token через review-ошибку.
    from postify import cli

    class FailingReview(FakeContentReview):
        def show(self, package_id: int):
            raise OSError("TOKEN-SECRET at https://private.test/article")

    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(
        cli,
        "open_content_review",
        lambda configured_settings: run_once_context(FailingReview(_content_package())),
        raising=False,
    )

    result = runner.invoke(cli.app, ["content", "show", "7"])

    assert result.exit_code != 0
    assert "Не удалось показать контентный пакет" in result.output
    assert "Traceback" not in result.output
    assert "TOKEN-SECRET" not in result.output
    assert "private.test" not in result.output
