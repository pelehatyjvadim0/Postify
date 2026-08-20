from __future__ import annotations

from types import SimpleNamespace

import pytest

from postify.application.content.manual_operations import (
    ManualContentOperations,
    ReviewUnresolved,
)
from postify.application.delivery.manual_operations import (
    DeliveryNotRetryable,
    ManualDeliveryRetry,
)
from postify.domain.content.models import (
    ExecutionActor,
    ExecutionMode,
    ExecutionPurpose,
    InvalidContentTransition,
)


class ContentTargets:
    def __init__(
        self,
        *,
        attempt_status: str | None = "failed",
        package_status: str = "approved",
        unresolved: tuple[int, ...] = (),
    ) -> None:
        self.status = attempt_status
        self.package_status = package_status
        self.unresolved = unresolved

    def attempt_status(self, attempt_id: int) -> str | None:
        assert attempt_id == 41
        return self.status

    def awaiting_review_package_ids(self, *, limit: int) -> tuple[int, ...]:
        assert limit == 50
        return self.unresolved

    def get_package(self, package_id: int):
        if package_id == 404:
            raise LookupError(package_id)
        return SimpleNamespace(status=self.package_status)


class DeliveryTargets:
    def __init__(self, route_id: int | None) -> None:
        self.route_id = route_id

    def retryable_route_id(self, delivery_id: int) -> int | None:
        assert delivery_id == 73
        return self.route_id


@pytest.mark.parametrize("status", ["failed", "retry_scheduled"])
def test_retry_analysis_accepts_failed_and_scheduled_targets(status: str) -> None:
    context = ManualContentOperations(
        ContentTargets(attempt_status=status)  # type: ignore[arg-type]
    ).retry_analysis(41)

    assert context.mode is ExecutionMode.MANUAL
    assert context.actor is ExecutionActor.UI
    assert context.purpose is ExecutionPurpose.RETRY_ANALYSIS
    assert context.target_attempt_id == 41


@pytest.mark.parametrize("status", [None, "processing", "packaged", "retried"])
def test_retry_analysis_rejects_missing_or_ineligible_target(status: str | None) -> None:
    action = ManualContentOperations(
        ContentTargets(attempt_status=status)  # type: ignore[arg-type]
    )

    expected = LookupError if status is None else InvalidContentTransition
    with pytest.raises(expected):
        action.retry_analysis(41)


def test_load_more_reports_exact_unresolved_package_ids() -> None:
    action = ManualContentOperations(
        ContentTargets(unresolved=(7, 9))  # type: ignore[arg-type]
    )

    with pytest.raises(ReviewUnresolved) as raised:
        action.load_more()

    assert raised.value.package_ids == (7, 9)


@pytest.mark.parametrize(
    ("method", "status", "purpose"),
    [
        ("return_to_analysis", "rejected", ExecutionPurpose.RETURN_TO_ANALYSIS),
        ("regenerate_post", "awaiting_review", ExecutionPurpose.REGENERATE_POST),
        ("replace_media", "approved", ExecutionPurpose.REPLACE_MEDIA),
        ("publish_now", "approved", ExecutionPurpose.PUBLISH_NOW),
    ],
)
def test_package_commands_share_project_owned_status_eligibility(
    method: str, status: str, purpose: ExecutionPurpose
) -> None:
    action = ManualContentOperations(
        ContentTargets(package_status=status)  # type: ignore[arg-type]
    )

    context = getattr(action, method)(17)

    assert context.purpose is purpose
    assert context.target_package_id == 17


def test_delivery_retry_resolves_route_in_shared_action() -> None:
    route_id, context = ManualDeliveryRetry(
        DeliveryTargets(19)  # type: ignore[arg-type]
    ).prepare(73)

    assert route_id == 19
    assert context.purpose is ExecutionPurpose.RETRY_DELIVERY
    assert context.target_delivery_id == 73


def test_delivery_retry_rejects_non_retryable_target() -> None:
    with pytest.raises(DeliveryNotRetryable):
        ManualDeliveryRetry(DeliveryTargets(None)).prepare(73)  # type: ignore[arg-type]
