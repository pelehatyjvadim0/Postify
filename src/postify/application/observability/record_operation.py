from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Generic, Protocol, TypeVar

from postify.application.ports.operation_run_repository import OperationRunRepository
from postify.domain.observability.models import (
    OperationKind,
    validate_operation_failure_code,
    validate_operation_outcome,
)

T = TypeVar("T")


class _Action(Protocol[T]):
    def execute(self) -> T: ...


class RecordedAction(Generic[T]):
    """
    Оборачивает действие строкой журнала операций.

    Журнал — единственный источник статуса для UI, поэтому running-строка
    появляется до запуска действия, а её терминальная запись не содержит текста
    исключения: в failure_code попадает только фиксированный безопасный код.
    """

    def __init__(
        self,
        action: _Action[T],
        journal: OperationRunRepository,
        *,
        operation: OperationKind,
        success_outcome: str | Callable[[T], str],
        failure_code: str,
        mode: str = "automatic",
        actor: str = "scheduler",
        result_metadata: Callable[[T], Mapping[str, object]] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._action = action
        self._journal = journal
        self._operation = operation
        self._success_outcome = success_outcome
        self._failure_code = validate_operation_failure_code(operation, failure_code)
        self._mode = mode
        self._actor = actor
        self._result_metadata = result_metadata
        self._clock = clock

    def execute(self) -> T:
        run_id = self._journal.start(
            self._operation,
            now=self._clock(),
            mode=self._mode,
            actor=self._actor,
        )
        try:
            result = self._action.execute()
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException:
            try:
                self._journal.fail(
                    run_id, failure_code=self._failure_code, now=self._clock()
                )
            except BaseException:
                pass
            raise
        outcome = (
            self._success_outcome(result)
            if callable(self._success_outcome)
            else self._success_outcome
        )
        validate_operation_outcome(self._operation, outcome)
        payload = dict(self._result_metadata(result)) if self._result_metadata else None
        self._journal.succeed(
            run_id, outcome=outcome, now=self._clock(), result=payload
        )
        return result

    def __getattr__(self, name: str):
        return getattr(self._action, name)
