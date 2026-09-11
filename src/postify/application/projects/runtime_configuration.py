from __future__ import annotations

from dataclasses import dataclass

from postify.domain.projects.models import (
    ChannelConnection,
    ContentProject,
    ProjectRubric,
)


@dataclass(frozen=True, slots=True)
class RuntimeChannel:
    connection: ChannelConnection
    encrypted_secret: str | None


@dataclass(frozen=True, slots=True)
class ProjectRuntimeGraph:
    """Проект со всем, что нужно конвейеру: рубрики и канал доставки."""

    project: ContentProject
    rubrics: tuple[ProjectRubric, ...]
    channel: RuntimeChannel | None

    def enabled_rubrics(self) -> tuple[ProjectRubric, ...]:
        return tuple(item for item in self.rubrics if item.enabled)

    def publication_channel(self) -> RuntimeChannel:
        if self.channel is None or not self.channel.connection.enabled:
            raise RuntimeError("publication_channel_unavailable")
        return self.channel
