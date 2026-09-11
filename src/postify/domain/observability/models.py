from __future__ import annotations

from enum import StrEnum


class OperationKind(StrEnum):
    GENERATE_POST = "generate_post"
    REGENERATE_POST = "regenerate_post"
    PUBLISH_ONCE = "publish_once"
    RETRY_DELIVERY = "retry_delivery"
    DERIVE_RULES = "derive_rules"
    CAPTION_MEDIA = "caption_media"


class OperationStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OperationMode(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


class OperationActor(StrEnum):
    SCHEDULER = "scheduler"
    USER = "user"


DELIVERY_OUTCOMES = frozenset(
    {
        "empty",
        "published",
        "cleanup_completed",
        "cleanup_pending",
        "retryable",
        "failed",
        "uncertain",
    }
)

OPERATION_OUTCOMES = {
    OperationKind.GENERATE_POST: frozenset({"completed", "empty"}),
    OperationKind.REGENERATE_POST: frozenset({"completed", "empty"}),
    OperationKind.PUBLISH_ONCE: DELIVERY_OUTCOMES,
    OperationKind.RETRY_DELIVERY: DELIVERY_OUTCOMES,
    OperationKind.DERIVE_RULES: frozenset({"completed", "empty"}),
    OperationKind.CAPTION_MEDIA: frozenset({"completed", "empty"}),
}

OPERATION_FAILURE_CODES = {kind: f"{kind.value}_failed" for kind in OperationKind}


def validate_operation_outcome(operation: OperationKind | str, outcome: str) -> str:
    if outcome not in OPERATION_OUTCOMES[OperationKind(operation)]:
        raise ValueError("Недопустимый outcome операции")
    return outcome


def validate_operation_failure_code(
    operation: OperationKind | str, failure_code: str
) -> str:
    if failure_code != OPERATION_FAILURE_CODES[OperationKind(operation)]:
        raise ValueError("Недопустимый failure code операции")
    return failure_code
