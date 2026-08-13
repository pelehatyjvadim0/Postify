from __future__ import annotations

from dataclasses import dataclass

from postify.application.ports.content_analyzer import GenerationBrief
from postify.domain.projects.models import (
    CallToAction,
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
    ctas: tuple[CallToAction, ...]
    channels: tuple[RuntimeChannel, ...]
    routes: tuple[PublicationRoute, ...]

    def effective_generation(self) -> EffectiveGeneration:
        formats = {item.id: item for item in self.formats if item.enabled}
        ctas = {item.id: item for item in self.ctas if item.enabled}
        route = next(
            (
                item
                for item in sorted(self.routes, key=lambda value: value.id)
                if item.enabled
                and item.format_id in formats
                and (item.cta_id is None or item.cta_id in ctas)
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
        cta = (
            ctas.get(route.cta_id)
            if route is not None and route.cta_id is not None
            else next(iter(sorted(ctas.values(), key=lambda value: value.id)), None)
        )
        cta_text = cta.text if cta is not None else "Без CTA"
        brief = GenerationBrief(
            topic=self.project.topic,
            language=self.project.language,
            audience=self.project.audience,
            format_instructions=content_format.instructions,
            cta=cta_text,
            cta_link_mode="none" if cta is None else cta.link_mode,
            cta_url=None if cta is None else cta.custom_url,
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
                "cta": None
                if cta is None
                else {
                    "id": cta.id,
                    "name": cta.name,
                    "text": cta.text,
                    "link_mode": cta.link_mode,
                    "custom_url": cta.custom_url,
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
