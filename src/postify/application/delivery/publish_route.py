from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Protocol

from postify.domain.delivery.models import PublishContentResult
from postify.domain.projects.models import ChannelConnection, PublicationRoute


class ChannelAdapter(Protocol):
    def publisher_for(self, channel: ChannelConnection) -> object: ...


class PublishContentAction(Protocol):
    def execute(self) -> PublishContentResult: ...


class PublishRoute:
    """Выбирает включённый маршрут, оставляя доставку общему action."""

    def __init__(
        self,
        *,
        routes: Iterable[PublicationRoute],
        channels: Iterable[ChannelConnection],
        channel_adapters: Mapping[str, ChannelAdapter],
        publish_content_factory: Callable[[object], PublishContentAction],
    ) -> None:
        self._routes = tuple(routes)
        self._channels = {channel.id: channel for channel in channels}
        self._channel_adapters = channel_adapters
        self._publish_content_factory = publish_content_factory

    def execute(self) -> PublishContentResult:
        route = next(
            (route for route in sorted(self._routes, key=lambda item: item.id) if route.enabled),
            None,
        )
        if route is None:
            raise LookupError("Нет включённого маршрута публикации")
        channel = self._channels.get(route.channel_id)
        if (
            channel is None
            or not channel.enabled
            or channel.project_id != route.project_id
        ):
            raise LookupError("Нет доступного канала публикации")
        adapter = self._channel_adapters.get(channel.provider)
        if adapter is None:
            raise LookupError("Нет адаптера канала публикации")
        publisher = adapter.publisher_for(channel)
        return self._publish_content_factory(publisher).execute()
