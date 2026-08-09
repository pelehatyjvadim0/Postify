from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest


NOW = datetime(2026, 8, 9, 21, 30, tzinfo=UTC)
MOSCOW = ZoneInfo("Europe/Moscow")


def _api():
    # RED API импортируется внутри helper, поэтому collection всего suite остаётся рабочей.
    from postify.application.observability.show_status import (
        RuntimeSnapshot,
        ShowOperationalStatus,
    )
    from postify.domain.observability.models import (
        GroupedState,
        OperationRunSummary,
        RawOperationalSnapshot,
    )

    return (
        GroupedState,
        OperationRunSummary,
        RawOperationalSnapshot,
        RuntimeSnapshot,
        ShowOperationalStatus,
    )


class SnapshotRepository:
    def __init__(self, snapshot) -> None:
        self.value = snapshot
        self.calls: list[tuple[date, datetime, datetime, int]] = []

    def snapshot(
        self,
        *,
        day: date,
        day_start: datetime,
        day_end: datetime,
        limit: int = 10,
    ):
        self.calls.append((day, day_start, day_end, limit))
        return self.value


def _group(code: str, count: int = 1, ids: tuple[int, ...] = ()):
    GroupedState, *_ = _api()
    return GroupedState(code=code, count=count, ids=ids)


def raw_snapshot(**overrides):
    _, _, RawSnapshot, _, _ = _api()
    defaults = {
        "candidate_total": 0,
        "candidate_undecided_ids": (),
        "candidate_decisions": (),
        "rejection_reasons": (),
        "content_attempts": (),
        "packages": (),
        "delivery": (),
        "delivery_ready_ids": (),
        "pending_cleanup_ids": (),
        "daily_analyses_started": 0,
        "daily_packages_created": 0,
        "published_today": 0,
        "selected_without_attempt_ids": (),
        "latest_packages": (),
        "latest_delivery_attempts": (),
        "latest_operation_runs": (),
    }
    defaults.update(overrides)
    return RawSnapshot(**defaults)


def runtime(**overrides):
    *_, RuntimeSnapshot, _ = _api()
    values = {
        "migrations_at_head": True,
        "run_once_service_active": False,
        "publish_once_service_active": False,
        "systemd_failures": (),
    }
    values.update(overrides)
    return RuntimeSnapshot(**values)


def report(snapshot, *, runtime_snapshot=None, **overrides):
    *_, ShowStatus = _api()
    repository = SnapshotRepository(snapshot)
    values = {
        "timezone": MOSCOW,
        "daily_target": 3,
        "analysis_limit": 5,
        "package_limit": 3,
        "clock": lambda: NOW,
    }
    values.update(overrides)
    action = ShowStatus(repository, **values)
    result = action.execute(runtime_snapshot or runtime())
    return result, repository


def _signal(report_value, code: str):
    return next(signal for signal in report_value.signals if signal.code == code)


def test_repository_receives_exact_local_day_as_half_open_utc_interval() -> None:
    # Поломка: UTC-day вместо Europe/Moscow считает другие публикации.
    result, repository = report(raw_snapshot())

    assert result.day == date(2026, 8, 10)
    assert repository.calls == [
        (
            date(2026, 8, 10),
            datetime(2026, 8, 9, 21, tzinfo=UTC),
            datetime(2026, 8, 10, 21, tzinfo=UTC),
            10,
        )
    ]


@pytest.mark.parametrize(
    "published_today, ready_ids, expected_deficit",
    [
        (0, (), 3),
        (1, (11,), 1),
        (3, (), 0),
        (5, (11, 12), 0),
    ],
)
def test_deficit_uses_only_today_published_and_claimable_ready(
    published_today: int,
    ready_ids: tuple[int, ...],
    expected_deficit: int,
) -> None:
    # Поломка: wrong target, published package без confirmation или blocked delivery считаются coverage.
    result, _ = report(
        raw_snapshot(
            published_today=published_today,
            delivery_ready_ids=ready_ids,
        )
    )

    assert result.daily_target == 3
    assert result.published_today == published_today
    assert result.delivery_ready == len(ready_ids)
    assert result.deficit == expected_deficit


@pytest.mark.parametrize(
    "snapshot_overrides, expected_reason",
    [
        ({"delivery": ("failed", 7)}, "delivery_blocked"),
        ({"packages": ("awaiting_review", 4)}, "review_backlog"),
        ({"daily_packages_created": 3}, "package_limit_reached"),
        ({"daily_analyses_started": 5}, "analysis_limit_reached"),
        ({"content_attempts": ("retry_scheduled", 9)}, "content_failures"),
        ({"selected_without_attempt_ids": (12,)}, "processing_backlog"),
        ({"candidate_undecided_ids": (2,)}, "selection_backlog"),
        ({}, "eligible_source_shortage"),
    ],
)
def test_each_deficit_cause_has_one_stable_safe_reason(
    snapshot_overrides: dict[str, object], expected_reason: str
) -> None:
    # Поломка: ветка taxonomy пропущена или возвращает произвольный текст.
    for category in ("delivery", "packages", "content_attempts"):
        if category in snapshot_overrides:
            code, entity_id = snapshot_overrides[category]
            snapshot_overrides[category] = (_group(code, ids=(entity_id,)),)
    result, _ = report(raw_snapshot(**snapshot_overrides))

    assert result.deficit_reasons == (expected_reason,)


def test_status_returns_all_applicable_reasons_in_fixed_order() -> None:
    # Поломка: возвращается одна причина вместо всех или порядок зависит от SQL.
    snapshot = raw_snapshot(
        candidate_undecided_ids=(2,),
        content_attempts=(
            _group("retry_scheduled", ids=(9,)),
            _group("processing", ids=(10,)),
        ),
        packages=(
            _group("awaiting_review", ids=(4,)),
            _group("failed", ids=(5,)),
        ),
        delivery=(_group("uncertain", ids=(7,)),),
        daily_analyses_started=5,
        daily_packages_created=3,
        selected_without_attempt_ids=(12,),
    )

    result, _ = report(snapshot)

    assert result.deficit_reasons == (
        "delivery_blocked",
        "review_backlog",
        "package_limit_reached",
        "analysis_limit_reached",
        "content_failures",
        "processing_backlog",
        "selection_backlog",
    )


def test_zero_deficit_has_explicit_none_reason_even_with_backlogs() -> None:
    # Поломка: при выполненном плане CLI всё ещё объясняет несуществующий deficit.
    result, _ = report(
        raw_snapshot(
            published_today=3,
            packages=(_group("awaiting_review", ids=(4,)),),
        )
    )

    assert result.deficit == 0
    assert result.deficit_reasons == ("none",)


@pytest.mark.parametrize(
    "category, unknown_code, entity_id",
    [
        ("candidate_decisions", "future_decision", 31),
        ("content_attempts", "future_attempt", 32),
        ("packages", "future_package", 33),
        ("delivery", "future_delivery", 34),
    ],
)
def test_unknown_persisted_status_is_a_critical_signal(
    category: str, unknown_code: str, entity_id: int
) -> None:
    # Поломка: unknown status silently ignored и оператор видит healthy state.
    unknown_group = _group(unknown_code, ids=(entity_id,))
    result, _ = report(raw_snapshot(**{category: (unknown_group,)}))

    signal = _signal(result, "unknown_persisted_state")
    assert signal.severity == "critical"
    assert signal.count == 1
    assert signal.ids == unknown_group.ids


@pytest.mark.parametrize(
    "category, state_code, signal_code, expected_ids",
    [
        ("delivery", "uncertain", "delivery_uncertain", (7,)),
        ("delivery", "failed", "delivery_failed", (8,)),
        ("delivery", "retryable", "delivery_retryable", (9,)),
        ("pending_cleanup_ids", None, "media_cleanup_pending", (10,)),
        ("content_attempts", "failed", "content_attempt_failed", (11,)),
        ("packages", "failed", "content_package_failed", (12,)),
        ("packages", "awaiting_review", "review_required", (13,)),
    ],
)
def test_persisted_operational_problem_emits_safe_signal(
    category: str,
    state_code: str | None,
    signal_code: str,
    expected_ids: tuple[int, ...],
) -> None:
    # Поломка: persisted failure/backlog не виден или сигнал не указывает entity ID.
    value = (
        expected_ids if state_code is None else (_group(state_code, ids=expected_ids),)
    )
    result, _ = report(raw_snapshot(**{category: value}))

    signal = _signal(result, signal_code)
    assert signal.severity == (
        "critical" if signal_code == "delivery_uncertain" else "warning"
    )
    assert signal.count == len(expected_ids)
    assert signal.ids == expected_ids


def test_running_operation_is_unfinished_only_without_matching_active_service() -> None:
    # Поломка: любой running помечается как падение или inactive service скрывает stale run.
    _, OperationRun, *_ = _api()
    run = OperationRun(21, "run_once", "running", None, None, None, started_at=NOW)
    snapshot = raw_snapshot(latest_operation_runs=(run,))

    inactive, _ = report(snapshot)
    active, _ = report(snapshot, runtime_snapshot=runtime(run_once_service_active=True))

    assert _signal(inactive, "operation_unfinished").ids == (21,)
    assert all(signal.code != "operation_unfinished" for signal in active.signals)


def test_failed_operation_migration_and_systemd_failures_have_fixed_signals() -> None:
    # Поломка: runtime failure скрывает DB snapshot или печатает stderr.
    _, OperationRun, *_ = _api()
    failed = OperationRun(
        22,
        "publish_once",
        "failed",
        None,
        "publish_once_failed",
        NOW,
        started_at=datetime(2026, 8, 9, 20, tzinfo=UTC),
    )
    result, _ = report(
        raw_snapshot(latest_operation_runs=(failed,)),
        runtime_snapshot=runtime(
            migrations_at_head=False,
            systemd_failures=("postify-run-once.timer",),
        ),
    )

    assert _signal(result, "migration_not_at_head").severity == "critical"
    assert _signal(result, "systemd_probe_failed").severity == "warning"
    assert _signal(result, "operation_failed").ids == (22,)
    assert "postify-run-once.timer" not in repr(result.signals)


def test_healthy_snapshot_is_pure_and_has_no_problem_signals() -> None:
    # Поломка: status пишет row/claim/retry/cleanup или выдумывает problem.
    snapshot = raw_snapshot(published_today=3)
    before = repr(snapshot)

    result, repository = report(snapshot)

    assert repr(snapshot) == before
    assert repository.value is snapshot
    assert len(repository.calls) == 1
    assert result.signals == ()


def test_empty_snapshot_has_all_fixed_zero_entity_groups_in_design_order() -> None:
    # Поломка: empty DB рендерит пустые content/packages/delivery вместо явных нулей.
    result, _ = report(raw_snapshot(published_today=3))

    assert tuple(item.code for item in result.content_attempts) == (
        "processing",
        "retry_scheduled",
        "failed",
        "analyzed_not_selected",
        "packaged",
    )
    assert tuple(item.count for item in result.content_attempts) == (0, 0, 0, 0, 0)
    assert tuple(item.code for item in result.packages) == (
        "processing",
        "awaiting_review",
        "approved",
        "rejected",
        "failed",
        "published",
    )
    assert tuple(item.code for item in result.delivery) == (
        "ready",
        "sending",
        "retryable",
        "failed",
        "uncertain",
        "published",
        "cleanup_pending",
    )


def test_fixed_group_normalization_keeps_unknown_persisted_group() -> None:
    # Поломка: zero-fill скрывает неизвестный persisted status.
    result, _ = report(
        raw_snapshot(content_attempts=(_group("future_attempt", ids=(31,)),))
    )

    assert result.content_attempts[-1].code == "future_attempt"
    assert result.content_attempts[-1].ids == (31,)


def test_empty_snapshot_has_candidate_and_rejection_taxonomy_zero_groups() -> None:
    # Поломка: empty report скрывает selected/rejected и причины отклонения.
    result, _ = report(raw_snapshot(published_today=3))

    assert tuple((item.code, item.count) for item in result.candidate_decisions) == (
        ("selected", 0),
        ("rejected", 0),
    )
    assert tuple((item.code, item.count) for item in result.rejection_reasons) == (
        ("advertising", 0),
        ("out_of_scope", 0),
        ("hiring", 0),
        ("technical_without_use", 0),
    )


def test_candidate_normalization_keeps_unknown_reason_group() -> None:
    # Поломка: fixed rejection taxonomy замалчивает новое persisted reason.
    result, _ = report(
        raw_snapshot(rejection_reasons=(_group("future_reason", ids=(41,)),))
    )

    assert result.rejection_reasons[-1].code == "future_reason"


@pytest.mark.parametrize(
    ("runtime_overrides", "signal_code"),
    [
        ({"import_timer": "inactive"}, "import_timer_inactive"),
        ({"import_timer": "failed"}, "import_timer_inactive"),
        ({"publish_timer": "inactive"}, "publish_timer_inactive"),
        ({"publish_timer": "failed"}, "publish_timer_inactive"),
    ],
)
def test_inactive_or_failed_timer_emits_stable_warning(
    runtime_overrides: dict[str, object], signal_code: str
) -> None:
    # Поломка: inactive/failed timer показан healthy при полном DB report.
    result, _ = report(
        raw_snapshot(published_today=3), runtime_snapshot=runtime(**runtime_overrides)
    )

    signal = _signal(result, signal_code)
    assert signal.severity == "warning"
    assert signal.count == 1


def test_active_timers_and_unknown_failed_probe_emit_no_false_inactive_signal() -> None:
    # Поломка: active/unknown timer создаёт ложную operational problem.
    active, _ = report(
        raw_snapshot(published_today=3),
        runtime_snapshot=runtime(import_timer="active", publish_timer="active"),
    )
    unknown, _ = report(
        raw_snapshot(published_today=3),
        runtime_snapshot=runtime(import_timer="unknown", systemd_failures=("safe",)),
    )

    assert all(
        signal.code not in {"import_timer_inactive", "publish_timer_inactive"}
        for signal in active.signals
    )
    assert all(signal.code != "import_timer_inactive" for signal in unknown.signals)
    assert _signal(unknown, "systemd_probe_failed").count == 1
