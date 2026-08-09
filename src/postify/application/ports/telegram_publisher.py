from typing import Protocol

from postify.domain.delivery.models import DeliveryClaim, TelegramMessage


class TelegramPublisher(Protocol):
    def publish(self, claim: DeliveryClaim) -> TelegramMessage: ...
