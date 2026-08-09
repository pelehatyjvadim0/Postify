from __future__ import annotations

from datetime import UTC, datetime

import pytest


NOW = datetime(2026, 8, 9, 9, tzinfo=UTC)


def _models():
    # Импорт внутри test helper: отсутствующий Wave 5 API не ломает collection.
    from postify.domain.observability.models import (
        DeliveryAttemptSummary,
        GroupedState,
        OperationKind,
        OperationRunSummary,
        OperationStatus,
        PackageSummary,
        RawOperationalSnapshot,
    )

    return (
        DeliveryAttemptSummary,
        GroupedState,
        OperationKind,
        OperationRunSummary,
        OperationStatus,
        PackageSummary,
        RawOperationalSnapshot,
    )


def test_operation_enums_expose_only_supported_safe_codes() -> None:
    # Поломка: журнал принимает произвольный action/status или теряет один из двух action.
    _, _, OperationKind, _, OperationStatus, _, _ = _models()

    assert tuple(item.value for item in OperationKind) == ("run_once", "publish_once")
    assert tuple(item.value for item in OperationStatus) == (
        "running",
        "succeeded",
        "failed",
    )


def test_grouped_state_preserves_unknown_code_count_and_ids() -> None:
    # Поломка: unknown persisted status замалчивается или теряет entity IDs.
    _, GroupedState, *_ = _models()

    state = GroupedState(code="future_state", count=2, ids=(31, 29))

    assert state.code == "future_state"
    assert state.count == 2
    assert state.ids == (31, 29)


def test_raw_snapshot_is_immutable_and_has_explicit_zero_groups() -> None:
    # Поломка: read-model позволяет action менять DB-факты или опускает нулевые группы.
    *_, RawOperationalSnapshot = _models()

    snapshot = RawOperationalSnapshot()

    assert snapshot.candidate_total == 0
    assert snapshot.candidate_undecided_ids == ()
    assert snapshot.candidate_decisions == ()
    assert snapshot.rejection_reasons == ()
    assert snapshot.content_attempts == ()
    assert snapshot.packages == ()
    assert snapshot.delivery == ()
    assert snapshot.delivery_ready_ids == ()
    assert snapshot.pending_cleanup_ids == ()
    assert snapshot.latest_packages == ()
    assert snapshot.latest_delivery_attempts == ()
    assert snapshot.latest_operation_runs == ()
    with pytest.raises((AttributeError, TypeError)):
        snapshot.published_today = 99


@pytest.mark.parametrize(
    "factory_name, arguments",
    [
        ("package", (17, "approved")),
        ("attempt", (17, 2, "retryable", "network", None)),
        ("run", (4, "run_once", "running", None, None, None)),
    ],
)
def test_persisted_summaries_reject_naive_timestamps(
    factory_name: str, arguments: tuple[object, ...]
) -> None:
    # Поломка: UTC/local conversion молча принимает naive datetime.
    DeliveryAttempt, _, _, OperationRun, _, Package, _ = _models()
    naive = datetime(2026, 8, 9, 9)
    factories = {
        "package": lambda: Package(*arguments, created_at=naive),
        "attempt": lambda: DeliveryAttempt(*arguments, finished_at=naive),
        "run": lambda: OperationRun(*arguments, started_at=naive),
    }

    with pytest.raises(ValueError, match="timezone"):
        factories[factory_name]()


@pytest.mark.parametrize(
    "status, outcome, failure_code, finished_at",
    [
        ("running", "completed", None, NOW),
        ("succeeded", None, None, NOW),
        ("succeeded", "", None, NOW),
        ("failed", None, None, NOW),
        ("failed", None, "", NOW),
        ("failed", None, "run_once_failed", None),
    ],
)
def test_operation_run_summary_rejects_inconsistent_terminal_fields(
    status: str,
    outcome: str | None,
    failure_code: str | None,
    finished_at: datetime | None,
) -> None:
    # Поломка: persisted run сообщает невозможную terminal-комбинацию.
    _, _, _, OperationRun, *_ = _models()

    with pytest.raises(ValueError, match="terminal"):
        OperationRun(
            4,
            "run_once",
            status,
            outcome,
            failure_code,
            finished_at,
            started_at=NOW,
        )


@pytest.mark.parametrize(
    "status, outcome, failure_code, finished_at",
    [
        ("running", None, None, None),
        ("succeeded", "completed", None, NOW),
        ("failed", None, "run_once_failed", NOW),
    ],
)
def test_operation_run_summary_accepts_each_consistent_state(
    status: str,
    outcome: str | None,
    failure_code: str | None,
    finished_at: datetime | None,
) -> None:
    # Поломка: valid running/succeeded/failed строка не может попасть в status report.
    _, _, _, OperationRun, *_ = _models()

    run = OperationRun(
        4,
        "run_once",
        status,
        outcome,
        failure_code,
        finished_at,
        started_at=NOW,
    )

    assert (run.status, run.outcome, run.failure_code, run.finished_at) == (
        status,
        outcome,
        failure_code,
        finished_at,
    )


@pytest.mark.parametrize(
    ("operation", "outcome"),
    [
        ("run_once", "published"),
        ("publish_once", "completed"),
        ("publish_once", "free_text"),
    ],
)
def test_operation_run_summary_rejects_outcome_outside_operation_vocabulary(
    operation: str, outcome: str
) -> None:
    # Поломка: произвольный successful outcome попадает в durable report.
    _, _, _, OperationRun, *_ = _models()

    with pytest.raises(ValueError, match="outcome"):
        OperationRun(4, operation, "succeeded", outcome, None, NOW, started_at=NOW)
