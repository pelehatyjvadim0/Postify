from __future__ import annotations

from dataclasses import dataclass

from postify.domain.projects.models import (
    ContentFormat,
    ContentProject,
    ProjectConfiguration,
    PublicationRoute,
)


@dataclass(frozen=True, slots=True)
class BootstrapChannel:
    id: int
    project_id: int
    provider: str
    name: str
    enabled: bool
    configuration: dict[str, object]
    encrypted_secret: str
    connection_status: str


@dataclass(frozen=True, slots=True)
class ProjectBootstrapGraph:
    project: ContentProject
    formats: tuple[ContentFormat, ...]
    channels: tuple[BootstrapChannel, ...]
    routes: tuple[PublicationRoute, ...]


class BootstrapProject:
    def __init__(
        self,
        repository,
        source_registry,
        channel_registry,
        *,
        cipher,
        clock,
    ) -> None:
        self._repository = repository
        self._sources = source_registry
        self._channels = channel_registry
        self._cipher = cipher
        self._clock = clock

    def execute(self, settings, telegram):
        existing = self._repository.active_project()
        if existing is not None:
            return existing
        now = self._clock()
        configuration = ProjectConfiguration(
            analysis_batch_size=settings.content_batch_size,
            media_max_bytes=settings.content_media_max_bytes,
            analysis_timeout_seconds=settings.content_analysis_timeout_seconds,
            analysis_model=settings.content_model,
            source_language=settings.content_source_language,
            tone=settings.content_tone,
            analysis_reasoning_effort=settings.content_analysis_reasoning_effort,
        )
        project = ContentProject(
            1,
            "AutoPostTG",
            settings.project_topic,
            settings.project_language,
            settings.project_audience,
            settings.postify_timezone,
            configuration,
            now,
            now,
        )
        content_format = ContentFormat(
            1, 1, "Пост", "text", "Сохрани смысл, имена, числа и факты оригинала. Не добавляй утверждений. Подготовь естественный русский текст.", True
        )
        channels: tuple[BootstrapChannel, ...] = ()
        routes: tuple[PublicationRoute, ...] = ()
        if telegram is not None and self._cipher is not None:
            channel_configuration = self._channels.validate(
                "telegram", {"chat_id": telegram.telegram_chat_id}
            )
            channels = (
                BootstrapChannel(
                    1,
                    1,
                    "telegram",
                    "Telegram",
                    True,
                    channel_configuration,
                    self._cipher.encrypt(
                        telegram.telegram_bot_token.get_secret_value()
                    ),
                    "configured",
                ),
            )
            routes = (PublicationRoute(1, 1, 1, 1, True),)
        graph = ProjectBootstrapGraph(
            project, (content_format,), channels, routes
        )
        return self._repository.create_project_graph(graph)
