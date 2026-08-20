from __future__ import annotations

from dataclasses import dataclass

from postify.domain.projects.models import (
    CallToAction,
    ContentFormat,
    ContentProject,
    ProjectConfiguration,
    PublicationRoute,
    SourceConnection,
)


FORMAT_B_INSTRUCTIONS = (
    "Короткий хук с результатом или задачей читателя. Простое объяснение "
    "ценности, компактные возможности, механика только при необходимости, "
    "кому пригодится, честное ограничение и полезный следующий шаг."
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
    sources: tuple[SourceConnection, ...]
    formats: tuple[ContentFormat, ...]
    ctas: tuple[CallToAction, ...]
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
            selection_policy_version=settings.selection_policy_version,
            selection_rules=tuple(settings.selection_rules),
            topic_terms=tuple(settings.selection_topic_terms),
            topic_exclusion_terms=tuple(settings.selection_topic_exclusion_terms),
            advertising_terms=tuple(settings.selection_advertising_terms),
            hiring_terms=tuple(settings.selection_hiring_terms),
            technical_release_terms=tuple(
                settings.selection_technical_release_terms
            ),
            practical_terms=tuple(settings.selection_practical_terms),
            selection_freshness_days=settings.selection_freshness_days,
            daily_analysis_limit=settings.content_daily_analysis_limit,
            daily_package_limit=settings.content_daily_package_limit,
            priority_freshness_days=settings.content_priority_freshness_days,
            fresh_share_percent=settings.content_fresh_share_percent,
            reserve_share_percent=settings.content_reserve_share_percent,
            review_required=settings.content_review_required,
            article_max_bytes=settings.content_article_max_bytes,
            media_max_bytes=settings.content_media_max_bytes,
            analysis_timeout_seconds=settings.content_codex_timeout_seconds,
            analysis_model=getattr(
                settings, "content_codex_model", "gpt-5.6-luna"
            ),
            analysis_reasoning_effort=getattr(
                settings, "content_codex_reasoning_effort", "high"
            ),
        )
        project = ContentProject(
            1,
            "Технологии просто",
            settings.hn_query,
            settings.selection_language,
            settings.selection_audience,
            settings.postify_timezone,
            configuration,
            now,
            now,
        )
        source_configuration = self._sources.validate(
            "hn_algolia",
            {
                "url": settings.hn_algolia_url,
                "query": settings.hn_query,
                "tags": settings.hn_tags,
                "hits": settings.hn_hits_per_page,
            },
        )
        source = SourceConnection(
            1,
            1,
            "hn_algolia",
            "Hacker News",
            True,
            source_configuration,
            settings.postify_on_calendar,
        )
        content_format = ContentFormat(
            1, 1, "Практический разбор B", "text", FORMAT_B_INSTRUCTIONS, True
        )
        cta = CallToAction(
            1,
            1,
            "Полезный источник",
            "Открыть источник",
            "source",
            None,
            True,
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
            routes = (PublicationRoute(1, 1, 1, 1, 1, True),)
        graph = ProjectBootstrapGraph(
            project, (source,), (content_format,), (cta,), channels, routes
        )
        return self._repository.create_project_graph(graph)
