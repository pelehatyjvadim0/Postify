from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Generic, Protocol, TypeVar

from postify.application.ports.operation_run_repository import OperationRunRepository
from postify.application.content.process_content import ProcessContentResult
from postify.application.jobs.run_once import RunOnceResult
from postify.domain.content.models import AUTOMATIC_CONTEXT, ExecutionContext
from postify.domain.observability.models import (
    OperationKind,
    validate_operation_failure_code,
    validate_operation_outcome,
)

T = TypeVar("T")


def content_operation_metadata(
    result: ProcessContentResult | None,
) -> dict[str, object]:
    if result is None:
        return {
            "codex_model": None,
            "codex_reasoning_effort": None,
            "materials_taken": 0,
            "packages_created": 0,
        }
    return {
        "codex_model": result.codex_model,
        "codex_reasoning_effort": result.codex_reasoning_effort,
        "materials_taken": result.materials_taken,
        "packages_created": result.packages_created,
    }


def run_once_operation_metadata(result: object) -> dict[str, object]:
    if not isinstance(result, RunOnceResult):
        return content_operation_metadata(None)
    content_result = result.content_result
    if content_result is not None and not isinstance(content_result, ProcessContentResult):
        raise TypeError("run_once content result has unexpected type")
    return content_operation_metadata(content_result)


class _Action(Protocol[T]):
    def execute(self) -> T: ...


class RecordedAction(Generic[T]):
    def __init__(
        self,
        action: _Action[T],
        journal: OperationRunRepository,
        *,
        operation: OperationKind,
        success_outcome: str | Callable[[T], str],
        failure_code: str,
        execution_context: ExecutionContext = AUTOMATIC_CONTEXT,
        result_metadata: Callable[[T], Mapping[str, object]] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._action = action
        self._journal = journal
        self._operation = operation
        self._success_outcome = success_outcome
        self._failure_code = validate_operation_failure_code(operation, failure_code)
        self._execution_context = execution_context
        self._result_metadata = result_metadata
        self._clock = clock

    def execute(self) -> T:
        run_id = self._journal.start(
            self._operation,
            now=self._clock(),
            mode=self._execution_context.mode.value,
            actor=self._execution_context.actor.value,
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
        metadata = dict(self._result_metadata(result)) if self._result_metadata else {}
        self._journal.succeed(
            run_id, outcome=outcome, now=self._clock(), **metadata
        )
        return result

    def __getattr__(self, name: str):
        return getattr(self._action, name)
