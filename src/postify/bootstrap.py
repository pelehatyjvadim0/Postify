from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.resources import as_file, files
from pathlib import Path
from time import monotonic, sleep

import httpx
import subprocess
import tempfile
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from postify.adapters.sources.hn_algolia import HnAlgoliaCandidateSource
from postify.application.ingestion.import_candidates import ImportCandidates
from postify.application.jobs.run_once import RunOnce
from postify.application.selection.select_candidates import SelectCandidates
from postify.config import Settings, TelegramSettings
from postify.domain.candidates.selection import SelectionProfile
from postify.domain.candidates.statuses import RejectionRule
from postify.infrastructure.database.engine import create_engine_from_settings
from postify.infrastructure.repositories.sqlalchemy_candidates import (
    SqlAlchemyCandidateRepository,
)
from postify.infrastructure.repositories.sqlalchemy_decisions import (
    SqlAlchemyDecisionRepository,
)


def open_content_review(settings: Settings):
    """Открывает review-зависимости; фабрика отделена для CLI и тестов."""
    from contextlib import contextmanager
    from postify.application.content.review_content import ReviewContent
    from postify.adapters.http.public_url_policy import PublicHttpUrlPolicy
    from postify.adapters.media.local_media_provider import LocalMediaProvider
    from postify.infrastructure.repositories.sqlalchemy_content import (
        SqlAlchemyContentRepository,
    )

    @contextmanager
    def opened():
        engine = create_engine_from_settings(settings)
        client = httpx.Client()
        try:
            yield ReviewContent(
                SqlAlchemyContentRepository(sessionmaker(engine)),
                LocalMediaProvider(
                    client,
                    settings.content_media_dir,
                    settings.content_media_max_bytes,
                    None,
                    url_policy=PublicHttpUrlPolicy(),
                ),
                clock=lambda: datetime.now(UTC),
            )
        finally:
            client.close()
            engine.dispose()

    return opened()


@contextmanager
def open_publish_once(settings: Settings, telegram: TelegramSettings):
    from postify.adapters.http.public_url_policy import PublicHttpUrlPolicy
    from postify.adapters.media.local_media_provider import LocalMediaProvider
    from postify.adapters.telegram.bot_api import TelegramBotApiPublisher
    from postify.application.delivery.publish_content import PublishContent
    from postify.application.observability.record_operation import RecordedAction
    from postify.domain.observability.models import OperationKind
    from postify.infrastructure.repositories.sqlalchemy_delivery import SqlAlchemyDeliveryRepository
    from postify.infrastructure.repositories.sqlalchemy_observability import SqlAlchemyOperationRunRepository

    engine = create_engine_from_settings(settings)
    client: httpx.Client | None = None
    try:
        client = httpx.Client(timeout=telegram.telegram_timeout_seconds)
        media = LocalMediaProvider(client, settings.content_media_dir, settings.content_media_max_bytes, None, url_policy=PublicHttpUrlPolicy())
        action = PublishContent(
            SqlAlchemyDeliveryRepository(sessionmaker(engine)),
            TelegramBotApiPublisher(client, bot_token=telegram.telegram_bot_token.get_secret_value(), chat_id=telegram.telegram_chat_id),
            media,
            timeout_seconds=telegram.telegram_timeout_seconds,
            clock=lambda: datetime.now(UTC),
        )
        yield RecordedAction(
            action,
            SqlAlchemyOperationRunRepository(sessionmaker(engine)),
            operation=OperationKind.PUBLISH_ONCE,
            success_outcome=lambda result: result.outcome,
            failure_code="publish_once_failed",
        )
    finally:
        if client is not None:
            client.close()
        engine.dispose()


class DatabaseUnavailableError(RuntimeError):
    """PostgreSQL не стал доступен до истечения заданного времени."""


@dataclass(frozen=True, slots=True)
class _ImportResources:
    source: HnAlgoliaCandidateSource
    session_factory: sessionmaker[Session]
    client: httpx.Client
    url_policy: object


@contextmanager
def _open_import_resources(
    settings: Settings, *, transport: httpx.BaseTransport | None = None
) -> Iterator[_ImportResources]:
    engine = create_engine_from_settings(settings)
    client: httpx.Client | None = None
    try:
        from postify.adapters.http.public_url_policy import (
            PublicHttpTransport,
            PublicHttpUrlPolicy,
        )

        policy = PublicHttpUrlPolicy()
        client = httpx.Client(
            timeout=httpx.Timeout(10.0),
            transport=transport or PublicHttpTransport(policy=policy),
        )
        yield _ImportResources(
            source=HnAlgoliaCandidateSource(
                client=client,
                url=settings.hn_algolia_url,
                query=settings.hn_query,
                tags=settings.hn_tags,
                hits=settings.hn_hits_per_page,
            ),
            session_factory=sessionmaker(engine),
            client=client,
            url_policy=policy,
        )
    finally:
        if client is not None:
            client.close()
        engine.dispose()


@contextmanager
def open_importer(
    settings: Settings, *, transport: httpx.BaseTransport | None = None
) -> Iterator[ImportCandidates]:
    with _open_import_resources(settings, transport=transport) as resources:
        yield ImportCandidates(
            resources.source,
            SqlAlchemyCandidateRepository(resources.session_factory),
        )


def selection_profile_from_settings(settings: Settings) -> SelectionProfile:
    return SelectionProfile(
        version=settings.selection_policy_version,
        language=settings.selection_language,
        audience=settings.selection_audience,
        rules=tuple(RejectionRule(rule) for rule in settings.selection_rules),
        topic_terms=settings.selection_topic_terms,
        topic_exclusion_terms=settings.selection_topic_exclusion_terms,
        advertising_terms=settings.selection_advertising_terms,
        hiring_terms=settings.selection_hiring_terms,
        technical_release_terms=settings.selection_technical_release_terms,
        practical_terms=settings.selection_practical_terms,
        freshness_window=timedelta(days=settings.selection_freshness_days),
    )


@contextmanager
def open_run_once(
    settings: Settings, *, transport: httpx.BaseTransport | None = None
) -> Iterator[RunOnce]:
    from postify.application.observability.record_operation import RecordedAction
    from postify.domain.observability.models import OperationKind
    from postify.infrastructure.repositories.sqlalchemy_observability import SqlAlchemyOperationRunRepository
    profile = selection_profile_from_settings(settings)
    with _open_import_resources(settings, transport=transport) as resources:
        action = RunOnce(
            ImportCandidates(
                resources.source,
                SqlAlchemyCandidateRepository(resources.session_factory),
            ),
            SelectCandidates(
                SqlAlchemyDecisionRepository(resources.session_factory),
                profile,
                lambda: datetime.now(UTC),
            ),
            _content_processor(settings, resources)
            if callable(resources.session_factory)
            else None,
        )
        if not callable(resources.session_factory):
            # Тестовая lifecycle-граница без SQL session остаётся прежней.
            yield action
        else:
            yield RecordedAction(
                action,
                SqlAlchemyOperationRunRepository(resources.session_factory),
                operation=OperationKind.RUN_ONCE,
                success_outcome="completed",
                failure_code="run_once_failed",
            )


def _content_processor(settings: Settings, resources: _ImportResources):
    from postify.adapters.ai.codex_content_analyzer import CodexContentAnalyzer
    from postify.adapters.articles.http_article_extractor import HttpArticleExtractor
    from postify.adapters.media.local_media_provider import LocalMediaProvider
    from postify.adapters.media.wikimedia import WikimediaImageSearch
    from postify.adapters.http.public_url_policy import PublicHttpUrlPolicy
    from postify.application.content.process_content import ProcessContent
    from postify.domain.content.models import ContentLimits
    from postify.infrastructure.repositories.sqlalchemy_content import (
        SqlAlchemyContentRepository,
    )

    policy = getattr(resources, "url_policy", None) or PublicHttpUrlPolicy()
    return ProcessContent(
        SqlAlchemyContentRepository(resources.session_factory),
        HttpArticleExtractor(
            client=resources.client,
            max_bytes=settings.content_article_max_bytes,
            url_policy=policy,
        ),
        CodexContentAnalyzer(
            lambda argv, **kwargs: subprocess.run(argv, check=False, **kwargs),
            Path.cwd(),
            settings.content_codex_timeout_seconds,
            _codex_work_dir(Path.cwd(), Path(settings.content_media_dir)),
        ),
        LocalMediaProvider(
            resources.client,
            settings.content_media_dir,
            settings.content_media_max_bytes,
            WikimediaImageSearch(client=resources.client),
            url_policy=policy,
        ),
        limits=ContentLimits(
            settings.content_daily_analysis_limit,
            settings.content_daily_package_limit,
            settings.content_priority_freshness_days,
            settings.content_fresh_share_percent,
            settings.content_reserve_share_percent,
        ),
        review_required=settings.content_review_required,
        timezone=settings.postify_timezone,
        clock=lambda: datetime.now(UTC),
    )


def _codex_work_dir(repository: Path, media_dir: Path) -> Path:
    repository = repository.resolve()
    media_dir = media_dir.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    for candidate in (temp_root / "postify-codex", temp_root.parent / "postify-codex"):
        resolved = candidate.resolve()
        if _paths_are_disjoint(resolved, repository) and _paths_are_disjoint(
            resolved, media_dir
        ):
            return resolved
    raise RuntimeError("codex_work_unavailable")


def _paths_are_disjoint(first: Path, second: Path) -> bool:
    return not first.is_relative_to(second) and not second.is_relative_to(first)


def database_is_ready(settings: Settings) -> bool:
    engine = create_engine_from_settings(settings)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False
    finally:
        engine.dispose()


def wait_for_database(settings: Settings) -> None:
    deadline = monotonic() + settings.database_readiness_timeout_seconds
    while not database_is_ready(settings):
        if monotonic() >= deadline:
            raise DatabaseUnavailableError(
                "БД недоступна до истечения времени ожидания"
            )
        sleep(0.1)


def migrations_at_head(settings: Settings) -> bool:
    migration_resources = files("postify.infrastructure.database.migrations")
    with as_file(migration_resources) as migration_path:
        alembic_config = Config()
        alembic_config.set_main_option("script_location", str(migration_path))
        expected_heads = set(ScriptDirectory.from_config(alembic_config).get_heads())
        engine = create_engine_from_settings(settings)
        try:
            with engine.connect() as connection:
                current_heads = set(
                    MigrationContext.configure(connection).get_current_heads()
                )
            return current_heads == expected_heads
        finally:
            engine.dispose()


def candidate_count(settings: Settings) -> int:
    engine = create_engine_from_settings(settings)
    try:
        return SqlAlchemyCandidateRepository(sessionmaker(engine)).count()
    finally:
        engine.dispose()


@contextmanager
def open_operational_status(settings: Settings):
    from postify.application.observability.show_status import ShowOperationalStatus
    from postify.infrastructure.repositories.sqlalchemy_observability import SqlAlchemyOperationalStatusRepository
    from zoneinfo import ZoneInfo

    engine = create_engine_from_settings(settings)
    try:
        yield ShowOperationalStatus(
            SqlAlchemyOperationalStatusRepository(sessionmaker(engine)),
            timezone=ZoneInfo(settings.postify_timezone),
            daily_target=3,
            analysis_limit=settings.content_daily_analysis_limit,
            package_limit=settings.content_daily_package_limit,
            clock=lambda: datetime.now(UTC),
        )
    finally:
        engine.dispose()
