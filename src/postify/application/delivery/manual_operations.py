from __future__ import annotations

from dataclasses import dataclass

from postify.application.ports.delivery_repository import DeliveryRepository


class DeliveryNotRetryable(ValueError):
    """Повтор отправки для этой доставки недопустим."""


@dataclass(frozen=True, slots=True)
class ManualDeliveryRetry:
    """Проверяет, что доставка проекта действительно ждёт повтора."""

    repository: DeliveryRepository

    def prepare(self, delivery_id: int) -> None:
        if not self.repository.is_retryable(delivery_id):
            raise DeliveryNotRetryable("delivery_not_retryable")
