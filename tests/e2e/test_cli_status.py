from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace

from typer.testing import CliRunner


runner = CliRunner()
NOW = datetime(2026, 8, 9, 9, tzinfo=UTC)


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        postgresql_systemd_unit="postgresql-custom.service",
        postify_timezone="Europe/Moscow",
        content_daily_analysis_limit=5,
        content_daily_package_limit=3,
    )


class FakeSystemd:
    def __init__(self, *, failing_unit: str | None = None) -> None:
        self.failing_unit = failing_unit

    def active_state(self, unit: str) -> str:
        if unit == self.failing_unit:
            raise OSError("SENTINEL systemctl stderr /private/path")
        return {
            "postgresql-custom.service": "active",
            "postify-run-once.timer": "active",
            "postify-publish-once.timer": "active",
            "postify-run-once.service": "inactive",
            "postify-publish-once.service": "inactive",
        }[unit]

    def timer_properties(self) -> dict[str, str]:
        return {"LastTriggerUSec": "2026-08-09T09:00:00+03:00", "NextElapseUSecRealtime": "2026-08-09T12:00:00+03:00"}

    def publish_timer_properties(self) -> dict[str, str]:
        if self.failing_unit == "postify-publish-once.timer":
            raise OSError("SENTINEL publish timer stderr")
        return {"LastTriggerUSec": "2026-08-09T08:00:00+03:00", "NextElapseUSecRealtime": "2026-08-09T11:00:00+03:00"}


class FakeStatusAction:
    def __init__(self, report) -> None:
        self.report = report
        self.runtimes: list[object] = []

    def execute(self, runtime):
        self.runtimes.append(runtime)
        return self.report


@contextmanager
def opened(action):
    yield action


def _report(*, signals=()):
    def group(code: str, count: int) -> SimpleNamespace:
        return SimpleNamespace(code=code, count=count, ids=())

    return SimpleNamespace(
        day=date(2026, 8, 9),
        timezone="Europe/Moscow",
        candidate_total=9,
        candidate_undecided=0,
        candidate_decisions=(group("selected", 9), group("rejected", 0)),
        content_attempts=(group("processing", 1), group("failed", 0), group("packaged", 1)),
        packages=(group("awaiting_review", 1), group("approved", 0), group("published", 1)),
        delivery=(group("ready", 0), group("published", 1), group("uncertain", 0)),
        latest_packages=(SimpleNamespace(package_id=1, status="published", created_at=NOW),),
        latest_delivery_attempts=(
            SimpleNamespace(
                package_id=1,
                attempt_no=1,
                outcome="published",
                code=None,
                finished_at=NOW,
                message_id=6,
            ),
        ),
        daily_target=3,
        published_today=1,
        delivery_ready=0,
        deficit=2,
        deficit_reasons=("processing_backlog",),
        latest_operation_runs=(
            SimpleNamespace(
                run_id=4,
                operation="publish_once",
                status="succeeded",
                outcome="empty",
                failure_code=None,
                started_at=NOW,
                finished_at=NOW,
            ),
        ),
        signals=signals,
    )


def _configure(monkeypatch, *, action, systemd=None, database_ready=True, at_head=True):
    from postify import cli

    monkeypatch.setattr(cli, "Settings", settings)
    monkeypatch.setattr(
        cli,
        "TelegramSettings",
        lambda: (_ for _ in ()).throw(AssertionError("status must not load Telegram")),
    )
    monkeypatch.setattr(cli, "create_systemd_controller", lambda configured: systemd or FakeSystemd())
    monkeypatch.setattr(cli, "database_is_ready", lambda configured: database_ready)
    monkeypatch.setattr(cli, "candidate_count", lambda configured: 9)
    monkeypatch.setattr(cli, "migrations_at_head", lambda configured: at_head)
    monkeypatch.setattr(
        cli,
        "open_operational_status",
        lambda configured: opened(action),
        raising=False,
    )
    return cli


def test_status_prints_complete_deterministic_report_without_sensitive_fields(monkeypatch) -> None:
    # Поломка: CLI опускает section/zero/history/deficit или печатает DB payload.
    action = FakeStatusAction(_report())
    cli = _configure(monkeypatch, action=action)

    result = runner.invoke(cli.app, ["status"])

    assert result.exit_code == 0
    for expected in (
        "Система",
        "PostgreSQL: доступна; migrations=head",
        "import timer: active",
        "publish timer: active",
        "Сущности",
        "candidates: total=9; undecided=0; selected=9; rejected=0",
        "Последние пакеты (до 10)",
        "package=1; status=published; created_at=2026-08-09T12:00:00+03:00",
        "Доставка (последние 10 попыток)",
        "package=1; attempt=1; outcome=published",
        "message_id=6",
        "План на 2026-08-09 (Europe/Moscow)",
        "цель=3; опубликовано=1; готово=0; дефицит=2",
        "причины: processing_backlog",
        "Последние запуски (до 10)",
        "operation=publish_once; status=succeeded; outcome=empty",
        "Проблемы",
        "Проблем нет",
    ):
        assert expected in result.output
    for secret in ("SENTINEL", "private.invalid", "/media/", "telegram.org"):
        assert secret not in result.output
    assert len(action.runtimes) == 1


def test_one_systemd_probe_failure_keeps_database_snapshot_and_safe_signal(monkeypatch) -> None:
    # Поломка: one systemd failure скрывает DB или утекает stderr/unit argv.
    action = FakeStatusAction(
        _report(signals=(SimpleNamespace(severity="warning", code="systemd_probe_failed", count=1, ids=()),))
    )
    cli = _configure(
        monkeypatch,
        action=action,
        systemd=FakeSystemd(failing_unit="postify-publish-once.timer"),
    )

    result = runner.invoke(cli.app, ["status"])

    assert result.exit_code == 0
    assert "PostgreSQL: доступна" in result.output
    assert "candidates: total=9" in result.output
    assert "WARNING systemd_probe_failed" in result.output
    assert "SENTINEL" not in result.output
    assert "/private/path" not in result.output


def test_database_unavailable_prints_systemd_partial_report_and_safe_error(monkeypatch) -> None:
    # Поломка: DB failure выдумывает counts, теряет systemd facts или печатает DSN.
    action = FakeStatusAction(_report())
    cli = _configure(monkeypatch, action=action, database_ready=False)

    result = runner.invoke(cli.app, ["status"])

    assert result.exit_code == 1
    assert "import timer: active" in result.output
    assert "publish timer: active" in result.output
    assert "database_unavailable" in result.output
    assert "Не удалось получить состояние Postify" in result.output
    assert "candidates:" not in result.output
    assert action.runtimes == []
    assert "postgresql://" not in result.output
    assert "Traceback" not in result.output


def test_migration_not_at_head_prints_partial_report_and_exits_one(monkeypatch) -> None:
    # Поломка: stale schema показана healthy или CLI запускает несовместимый query.
    action = FakeStatusAction(_report())
    cli = _configure(monkeypatch, action=action, at_head=False)

    result = runner.invoke(cli.app, ["status"])

    assert result.exit_code == 1
    assert "migration_not_at_head" in result.output
    assert "import timer: active" in result.output
    assert action.runtimes == []
