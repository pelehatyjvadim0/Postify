from __future__ import annotations

from enum import StrEnum


class OperationKind(StrEnum):
    RUN_ONCE = "run_once"
    PUBLISH_ONCE = "publish_once"
    LOAD_MORE = "load_more"
    RETRY_ANALYSIS = "retry_analysis"
    RETURN_TO_ANALYSIS = "return_to_analysis"
    REGENERATE_POST = "regenerate_post"
    REPLACE_MEDIA = "replace_media"
    PUBLISH_NOW = "publish_now"
    RETRY_DELIVERY = "retry_delivery"
    MANUAL_SEARCH = "manual_search"


class OperationStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OperationMode(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


class OperationActor(StrEnum):
    SCHEDULER = "scheduler"
    UI = "ui"


OPERATION_OUTCOMES = {
    OperationKind.RUN_ONCE: frozenset({"completed"}),
    OperationKind.PUBLISH_ONCE: frozenset({"empty", "published", "cleanup_completed", "cleanup_pending", "retryable", "failed", "uncertain"}),
    OperationKind.LOAD_MORE: frozenset({"completed", "empty"}),
    OperationKind.RETRY_ANALYSIS: frozenset({"completed", "empty"}),
    OperationKind.RETURN_TO_ANALYSIS: frozenset({"completed", "empty"}),
    OperationKind.REGENERATE_POST: frozenset({"completed", "empty"}),
    OperationKind.REPLACE_MEDIA: frozenset({"completed", "empty"}),
    OperationKind.PUBLISH_NOW: frozenset({"empty", "published", "cleanup_completed", "cleanup_pending", "retryable", "failed", "uncertain"}),
    OperationKind.RETRY_DELIVERY: frozenset({"empty", "published", "cleanup_completed", "cleanup_pending", "retryable", "failed", "uncertain"}),
    OperationKind.MANUAL_SEARCH: frozenset({"completed"}),
}

OPERATION_FAILURE_CODES = {kind: f"{kind.value}_failed" for kind in OperationKind}


def validate_operation_outcome(operation: OperationKind | str, outcome: str) -> str:
    if outcome not in OPERATION_OUTCOMES[OperationKind(operation)]:
        raise ValueError("Недопустимый outcome операции")
    return outcome


def validate_operation_failure_code(operation: OperationKind | str, failure_code: str) -> str:
    if failure_code != OPERATION_FAILURE_CODES[OperationKind(operation)]:
        raise ValueError("Недопустимый failure code операции")
    return failure_code
