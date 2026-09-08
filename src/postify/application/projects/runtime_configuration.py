from __future__ import annotations

from dataclasses import dataclass

from postify.application.ports.content_analyzer import GenerationBrief
from postify.domain.projects.models import (
    ChannelConnection,
    ContentFormat,
    ContentProject,
    PublicationRoute,
    SourceConnection,
)


@dataclass(frozen=True, slots=True)
class RuntimeChannel:
    connection: ChannelConnection
    encrypted_secret: str | None


@dataclass(frozen=True, slots=True)
class EffectiveGeneration:
    brief: GenerationBrief
    snapshot: dict[str, object]


@dataclass(frozen=True, slots=True)
class ProjectRuntimeGraph:
    project: ContentProject
    sources: tuple[SourceConnection, ...]
    formats: tuple[ContentFormat, ...]
    channels: tuple[RuntimeChannel, ...]
    routes: tuple[PublicationRoute, ...]

    def effective_generation(self) -> EffectiveGeneration:
        formats = {item.id: item for item in self.formats if item.enabled}
        route = next(
            (
                item
                for item in sorted(self.routes, key=lambda value: value.id)
                if item.enabled
                and item.format_id in formats
            ),
            None,
        )
        content_format = (
            formats[route.format_id]
            if route is not None
            else next(iter(sorted(formats.values(), key=lambda value: value.id)), None)
        )
        if content_format is None:
            raise RuntimeError("generation_format_unavailable")
        brief = GenerationBrief(
            topic=self.project.topic,
            language=self.project.language,
            audience=self.project.audience,
            format_instructions=content_format.instructions,
            source_language=self.project.configuration.source_language,
            tone=self.project.configuration.tone,
        )
        return EffectiveGeneration(
            brief,
            {
                "topic": self.project.topic,
                "language": self.project.language,
                "audience": self.project.audience,
                "format": {
                    "id": content_format.id,
                    "name": content_format.name,
                    "kind": content_format.kind,
                    "instructions": content_format.instructions,
                },
            },
        )

    def enabled_route(self, route_id: int | None = None) -> PublicationRoute:
        route = next(
            (
                item
                for item in sorted(self.routes, key=lambda value: value.id)
                if item.enabled and (route_id is None or item.id == route_id)
            ),
            None,
        )
        if route is None:
            raise RuntimeError("publication_route_unavailable")
        return route

    def channel_for(self, route: PublicationRoute) -> RuntimeChannel:
        channel = next(
            (
                item
                for item in self.channels
                if item.connection.id == route.channel_id
                and item.connection.project_id == route.project_id
                and item.connection.enabled
            ),
            None,
        )
        if channel is None:
            raise RuntimeError("publication_channel_unavailable")
        return channel
