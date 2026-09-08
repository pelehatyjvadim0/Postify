from __future__ import annotations

from postify.domain.delivery.models import PublishContentResult
from postify.domain.projects.models import ChannelConnection, PublicationRoute


class DeliveryLog:
    def __init__(self) -> None:
        self.channel_ids: list[int] = []


class Publisher:
    def __init__(self, channel_id: int) -> None:
        self.channel_id = channel_id


class ChannelAdapter:
    def publisher_for(self, channel: ChannelConnection) -> Publisher:
        return Publisher(channel.id)


class PublishAction:
    def __init__(self, publisher: Publisher, deliveries: DeliveryLog) -> None:
        self._publisher = publisher
        self._deliveries = deliveries

    def execute(self) -> PublishContentResult:
        self._deliveries.channel_ids.append(self._publisher.channel_id)
        return PublishContentResult("published", package_id=7, message_id=101)


def _route(route_id: int, channel_id: int, *, enabled: bool) -> PublicationRoute:
    return PublicationRoute(route_id, 1, route_id, channel_id, enabled)


def _channel(channel_id: int, *, enabled: bool) -> ChannelConnection:
    return ChannelConnection(
        channel_id,
        1,
        "telegram",
        f"Канал {channel_id}",
        enabled,
        {"chat_id": "-1001"},
        True,
        "configured",
    )


def test_publish_route_uses_enabled_route_channel_and_returns_delivery_result() -> None:
    # Поломка: публикация выбирает отключённый route/channel либо теряет итог delivery action.
    from postify.application.delivery.publish_route import PublishRoute

    deliveries = DeliveryLog()
    action = PublishRoute(
        routes=(_route(1, 10, enabled=False), _route(2, 20, enabled=True)),
        channels=(_channel(10, enabled=True), _channel(20, enabled=True)),
        channel_adapters={"telegram": ChannelAdapter()},
        publish_content_factory=lambda publisher: PublishAction(publisher, deliveries),
    )

    result = action.execute()

    assert result == PublishContentResult("published", package_id=7, message_id=101)
    assert deliveries.channel_ids == [20]
