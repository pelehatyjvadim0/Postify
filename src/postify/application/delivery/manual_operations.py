from __future__ import annotations

from dataclasses import dataclass

from postify.application.ports.delivery_repository import DeliveryRepository
from postify.domain.content.models import (
    ExecutionActor,
    ExecutionContext,
    ExecutionMode,
    ExecutionPurpose,
)


class DeliveryNotRetryable(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ManualDeliveryRetry:
    """Resolve one project-owned retryable delivery for the shared publisher."""

    repository: DeliveryRepository

    def prepare(self, delivery_id: int) -> tuple[int, ExecutionContext]:
        route_id = self.repository.retryable_route_id(delivery_id)
        if route_id is None:
            raise DeliveryNotRetryable("delivery_not_retryable")
        return route_id, ExecutionContext(
            mode=ExecutionMode.MANUAL,
            actor=ExecutionActor.UI,
            purpose=ExecutionPurpose.RETRY_DELIVERY,
            target_delivery_id=delivery_id,
        )
