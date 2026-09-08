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

from postify.application.jobs.run_once import RunOnce
from postify.config import Settings, TelegramSettings
from postify.infrastructure.database.engine import create_engine_from_settings
from postify.infrastructure.repositories.sqlalchemy_candidates import (
    SqlAlchemyCandidateRepository,
)


def project_manual_content_operations(session_factory, project_id: int):
    """Compose project-scoped owner eligibility around the shared content port."""
    from postify.application.content.manual_operations import ManualContentOperations
    from postify.infrastructure.repositories.sqlalchemy_content import (
        SqlAlchemyContentRepository,
    )

    return ManualContentOperations(
        SqlAlchemyContentRepository(session_factory, project_id=project_id)
    )


def project_manual_delivery_retry(session_factory, project_id: int):
    """Compose project-scoped delivery retry eligibility around its shared port."""
    from postify.application.delivery.manual_operations import ManualDeliveryRetry
    from postify.infrastructure.repositories.sqlalchemy_delivery import (
        SqlAlchemyDeliveryRepository,
    )

    return ManualDeliveryRetry(
        SqlAlchemyDeliveryRepository(session_factory, project_id=project_id)
    )


def project_review_content(session_factory, project_id: int, media, *, clock):
    """Compose the shared review action without leaking persistence into web."""
    from postify.application.content.review_content import ReviewContent
    from postify.infrastructure.repositories.sqlalchemy_content import (
        SqlAlchemyContentRepository,
    )

    return ReviewContent(
        SqlAlchemyContentRepository(session_factory, project_id=project_id),
        media,
        clock=clock,
    )


def open_content_review(settings: Settings):
    """Открывает review-зависимости; фабрика отделена для CLI и тестов."""
    from contextlib import contextmanager
    from postify.application.content.review_content import ReviewContent
    from postify.adapters.media.local_media_provider import LocalMediaProvider
    from postify.infrastructure.repositories.sqlalchemy_content import (
        SqlAlchemyContentRepository,
    )

    @contextmanager
    def opened():
        engine = create_engine_from_settings(settings)
        try:
            yield ReviewContent(
                SqlAlchemyContentRepository(sessionmaker(engine)),
                LocalMediaProvider(settings.content_media_dir),
                clock=lambda: datetime.now(UTC),
            )
        finally:
            engine.dispose()

    return opened()


@contextmanager
def open_project_publish_once(
    settings: Settings,
    *,
    project_id: int,
    route_id: int | None = None,
    transport: httpx.BaseTransport | None = None,
    record_operation: bool = True,
    package_id: int | None = None,
    delivery_id: int | None = None,
):
    """Открывает publish из свежего project graph без env-секретов."""
    from postify.adapters.channels.registry import ChannelProviderRegistry
    from postify.adapters.media.local_media_provider import LocalMediaProvider
    from postify.application.delivery.publish_content import PublishContent
    from postify.application.observability.record_operation import RecordedAction
    from postify.domain.observability.models import OperationKind
    from postify.infrastructure.repositories.sqlalchemy_delivery import (
        SqlAlchemyDeliveryRepository,
    )
    from postify.infrastructure.repositories.sqlalchemy_observability import (
        SqlAlchemyOperationRunRepository,
    )
    from postify.infrastructure.repositories.sqlalchemy_projects import (
        SqlAlchemyProjectRepository,
    )
    from postify.infrastructure.security.secrets import SecretCipher

    engine = create_engine_from_settings(settings)
    client: httpx.Client | None = None
    try:
        sessions = sessionmaker(engine)
        graph = SqlAlchemyProjectRepository(sessions).runtime_graph(project_id)
        route = graph.enabled_route(route_id)
        runtime_channel = graph.channel_for(route)
        if settings.postify_secret_key is None:
            raise RuntimeError("secret_storage_unavailable")
        if runtime_channel.encrypted_secret is None:
            raise RuntimeError("publication_secret_unavailable")
        if runtime_channel.connection.connection_status not in {"configured", "ok"}:
            raise RuntimeError("publication_channel_unavailable")
        cipher = SecretCipher(settings.postify_secret_key.get_secret_value())
        secret = cipher.decrypt(runtime_channel.encrypted_secret)
        channel = runtime_channel.connection
        timeout_seconds = float(graph.project.configuration.analysis_timeout_seconds)
        client = httpx.Client(timeout=timeout_seconds, transport=transport)
        publisher = ChannelProviderRegistry().create_publisher(
            channel,
            decrypted_secret=secret,
            client=client,
        )
        channel_snapshot = {
            "id": channel.id,
            "name": channel.name,
            "provider": channel.provider,
            "configuration": dict(channel.configuration),
        }
        action = PublishContent(
            SqlAlchemyDeliveryRepository(
                sessions,
                project_id=project_id,
                route_id=route.id,
                channel_id=channel.id,
                channel_snapshot=channel_snapshot,
                package_id=package_id,
                delivery_id=delivery_id,
            ),
            publisher,
            LocalMediaProvider(settings.content_media_dir),
            timeout_seconds=timeout_seconds,
            clock=lambda: datetime.now(UTC),
        )
        if record_operation:
            yield RecordedAction(
                action,
                _for_project(
                    SqlAlchemyOperationRunRepository,
                    sessions,
                    project_id,
                ),
                operation=OperationKind.PUBLISH_ONCE,
                success_outcome=lambda result: result.outcome,
                failure_code="publish_once_failed",
            )
        else:
            yield action
    finally:
        if client is not None:
            client.close()
        engine.dispose()


class DatabaseUnavailableError(RuntimeError):
    """PostgreSQL не стал доступен до истечения заданного времени."""


@contextmanager
def open_run_once(
    settings: Settings,
    *,
    project_id: int = 1,
    transport: httpx.BaseTransport | None = None,
) -> Iterator[RunOnce]:
    with open_project_run_once(settings, project_id=project_id, transport=transport) as action:
        yield action


def project_source_import(settings, sessions, project_id, connection, client, *, telegram_reader=None):
    """Compose one source import with its persisted Telegram position."""
    from postify.adapters.sources.registry import SourceProviderRegistry
    from postify.application.ingestion.import_candidates import ImportCandidates

    reader = telegram_reader
    if reader is None and connection.provider == "telegram_group":
        if settings.telegram_api_id and settings.telegram_api_hash:
            from postify.adapters.sources.telegram_account import TelegramAccountReader
            from postify.infrastructure.repositories.sqlalchemy_telegram_source import SqlAlchemyTelegramSourceState

            state = SqlAlchemyTelegramSourceState(sessions, project_id, connection.id)
            reader = TelegramAccountReader(
                api_id=settings.telegram_api_id,
                api_hash=settings.telegram_api_hash.get_secret_value(),
                last_message_id=state.last_message_id,
                initialize=state.initialize,
            )
    return ImportCandidates(
        SourceProviderRegistry().create(connection, client=client, telegram_reader=reader),
        _for_project(SqlAlchemyCandidateRepository, sessions, project_id),
        source_connection_id=connection.id,
    )


@contextmanager
def open_project_run_once(
    settings: Settings,
    *,
    project_id: int,
    transport: httpx.BaseTransport | None = None,
    analyzer_runner=None,
    record_operation: bool = True,
    context=None,
    telegram_reader=None,
):
    """Открывает web/scheduler run из свежего project graph."""
    from postify.adapters.ai.codex_content_analyzer import CodexContentAnalyzer
    from postify.adapters.http.public_url_policy import (
        PublicHttpTransport,
        PublicHttpUrlPolicy,
    )
    from postify.adapters.sources.registry import SourceProviderRegistry
    from postify.application.content.process_content import ProcessContent
    from postify.application.ingestion.import_project_sources import ImportProjectSources
    from postify.application.observability.record_operation import (
        RecordedAction,
        run_once_operation_metadata,
    )
    from postify.domain.content.models import AUTOMATIC_CONTEXT
    from postify.domain.observability.models import OperationKind
    from postify.infrastructure.repositories.sqlalchemy_content import (
        SqlAlchemyContentRepository,
    )
    from postify.infrastructure.repositories.sqlalchemy_observability import (
        SqlAlchemyOperationRunRepository,
    )
    from postify.infrastructure.repositories.sqlalchemy_projects import (
        SqlAlchemyProjectRepository,
    )

    engine = create_engine_from_settings(settings)
    client: httpx.Client | None = None
    try:
        sessions = sessionmaker(engine)
        projects = SqlAlchemyProjectRepository(sessions)
        if project_id == 1 and projects.active_project() is None:
            from postify.application.projects.bootstrap_project import BootstrapProject
            from postify.adapters.channels.registry import ChannelProviderRegistry
            from postify.infrastructure.security.secrets import SecretCipher
            BootstrapProject(
                projects, SourceProviderRegistry(), ChannelProviderRegistry(),
                cipher=SecretCipher(settings.postify_secret_key.get_secret_value()) if settings.postify_secret_key else None,
                clock=lambda: datetime.now(UTC),
            ).execute(settings, None)
        graph = projects.runtime_graph(project_id)
        policy = PublicHttpUrlPolicy()
        client = httpx.Client(
            timeout=httpx.Timeout(10.0),
            transport=transport or PublicHttpTransport(policy=policy),
        )
        importer = ImportProjectSources(
            graph.sources,
            lambda connection: project_source_import(
                settings, sessions, project_id, connection, client,
                telegram_reader=telegram_reader,
            ),
        )
        effective = graph.effective_generation()
        configuration = graph.project.configuration
        if settings.content_analyzer == "gemini":
            from postify.adapters.ai.gemini_content_analyzer import GeminiContentAnalyzer
            analyzer = GeminiContentAnalyzer(
                client=client,
                api_key=settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else "",
                model=configuration.analysis_model,
                timeout=configuration.analysis_timeout_seconds,
            )
        else:
            analyzer = CodexContentAnalyzer(
                analyzer_runner
                or (lambda argv, **kwargs: subprocess.run(argv, check=False, **kwargs)),
                Path.cwd(), configuration.analysis_timeout_seconds,
                _codex_work_dir(Path.cwd(), Path(settings.content_media_dir)),
                model=configuration.analysis_model,
                reasoning_effort=configuration.analysis_reasoning_effort,
            )
        content = ProcessContent(
            SqlAlchemyContentRepository(sessions, project_id=project_id),
            analyzer,
            batch_size=configuration.analysis_batch_size,
            generation_brief=effective.brief,
            generation_snapshot=effective.snapshot,
            model=configuration.analysis_model,
            codex_model=configuration.analysis_model if settings.content_analyzer == "codex" else None,
            codex_reasoning_effort=configuration.analysis_reasoning_effort if settings.content_analyzer == "codex" else None,
            context=context or AUTOMATIC_CONTEXT,
            clock=lambda: datetime.now(UTC),
        )
        action = RunOnce(importer, content)
        if record_operation:
            yield RecordedAction(
                action,
                _for_project(
                    SqlAlchemyOperationRunRepository,
                    sessions,
                    project_id,
                ),
                operation=OperationKind.RUN_ONCE,
                success_outcome="completed",
                failure_code="run_once_failed",
                execution_context=context or AUTOMATIC_CONTEXT,
                result_metadata=run_once_operation_metadata,
            )
        else:
            yield action
    finally:
        if client is not None:
            client.close()
        engine.dispose()


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


def _for_project(factory, session_factory, project_id: int):
    """Retain default constructor compatibility while making non-default scope explicit."""
    if project_id == 1:
        return factory(session_factory)
    return factory(session_factory, project_id=project_id)
