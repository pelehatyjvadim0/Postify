from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class OperationKind(StrEnum):
    RUN_ONCE = "run_once"
    PUBLISH_ONCE = "publish_once"


class OperationStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


OPERATION_OUTCOMES = {
    OperationKind.RUN_ONCE: frozenset({"completed"}),
    OperationKind.PUBLISH_ONCE: frozenset(
        {
            "empty",
            "published",
            "cleanup_completed",
            "cleanup_pending",
            "retryable",
            "failed",
            "uncertain",
        }
    ),
}

OPERATION_FAILURE_CODES = {
    OperationKind.RUN_ONCE: "run_once_failed",
    OperationKind.PUBLISH_ONCE: "publish_once_failed",
}


def validate_operation_outcome(operation: OperationKind | str, outcome: str) -> str:
    kind = OperationKind(operation)
    if outcome not in OPERATION_OUTCOMES[kind]:
        raise ValueError("Недопустимый outcome операции")
    return outcome


def validate_operation_failure_code(
    operation: OperationKind | str, failure_code: str
) -> str:
    kind = OperationKind(operation)
    if failure_code != OPERATION_FAILURE_CODES[kind]:
        raise ValueError("Недопустимый failure code операции")
    return failure_code


def _positive(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} должен быть положительным")


def _aware(value: datetime | None, name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{name} должен содержать timezone")


@dataclass(frozen=True, slots=True)
class GroupedState:
    code: str
    count: int
    ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("Нужен код состояния")
        if type(self.count) is not int or self.count < 0:
            raise ValueError("count не может быть отрицательным")
        if any(type(value) is not int or value <= 0 for value in self.ids):
            raise ValueError("IDs должны быть положительными")


@dataclass(frozen=True, slots=True)
class PackageSummary:
    package_id: int
    status: str
    created_at: datetime

    def __post_init__(self) -> None:
        _positive(self.package_id, "package_id")
        _aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class DeliveryAttemptSummary:
    package_id: int
    attempt_no: int
    outcome: str
    code: str | None
    message_id: int | None
    finished_at: datetime

    def __post_init__(self) -> None:
        _positive(self.package_id, "package_id")
        _positive(self.attempt_no, "attempt_no")
        _aware(self.finished_at, "finished_at")
        if self.message_id is not None:
            _positive(self.message_id, "message_id")


@dataclass(frozen=True, slots=True)
class OperationRunSummary:
    run_id: int
    operation: OperationKind | str
    status: OperationStatus | str
    outcome: str | None
    failure_code: str | None
    finished_at: datetime | None
    started_at: datetime

    def __post_init__(self) -> None:
        _positive(self.run_id, "run_id")
        _aware(self.started_at, "started_at")
        _aware(self.finished_at, "finished_at")
        operation = OperationKind(self.operation)
        status = OperationStatus(self.status)
        object.__setattr__(self, "operation", operation.value)
        object.__setattr__(self, "status", status.value)
        terminal = (self.outcome, self.failure_code, self.finished_at)
        if status is OperationStatus.RUNNING:
            valid = terminal == (None, None, None)
        elif status is OperationStatus.SUCCEEDED:
            valid = (
                bool(self.outcome and self.outcome.strip())
                and self.failure_code is None
                and self.finished_at is not None
            )
        else:
            valid = (
                self.outcome is None
                and bool(self.failure_code and self.failure_code.strip())
                and self.finished_at is not None
            )
        if not valid:
            raise ValueError("Некорректные terminal поля operation run")
        if status is OperationStatus.SUCCEEDED:
            validate_operation_outcome(operation, self.outcome)
        if status is OperationStatus.FAILED:
            validate_operation_failure_code(operation, self.failure_code)


@dataclass(frozen=True, slots=True)
class RawOperationalSnapshot:
    candidate_total: int = 0
    candidate_undecided_ids: tuple[int, ...] = ()
    candidate_decisions: tuple[GroupedState, ...] = ()
    rejection_reasons: tuple[GroupedState, ...] = ()
    content_attempts: tuple[GroupedState, ...] = ()
    packages: tuple[GroupedState, ...] = ()
    delivery: tuple[GroupedState, ...] = ()
    delivery_ready_ids: tuple[int, ...] = ()
    pending_cleanup_ids: tuple[int, ...] = ()
    daily_analyses_started: int = 0
    daily_packages_created: int = 0
    published_today: int = 0
    selected_without_attempt_ids: tuple[int, ...] = ()
    latest_packages: tuple[PackageSummary, ...] = ()
    latest_delivery_attempts: tuple[DeliveryAttemptSummary, ...] = ()
    latest_operation_runs: tuple[OperationRunSummary, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "candidate_total",
            "daily_analyses_started",
            "daily_packages_created",
            "published_today",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} не может быть отрицательным")
        for name in (
            "candidate_undecided_ids",
            "delivery_ready_ids",
            "pending_cleanup_ids",
            "selected_without_attempt_ids",
        ):
            if any(
                type(value) is not int or value <= 0 for value in getattr(self, name)
            ):
                raise ValueError(f"{name} содержит неположительный ID")
