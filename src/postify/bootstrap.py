"""Сборка зависимостей вне веб-слоя: публикация, готовность БД и миграции.

Здесь нет ни одного знания про HTTP: фасад приложения и CLI берут отсюда
готовые действия с открытым соединением и сами решают, как их вызвать.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.resources import as_file, files
from time import monotonic, sleep

import httpx
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from postify.config import Settings
from postify.infrastructure.database.engine import create_engine_from_settings


class DatabaseUnavailableError(RuntimeError):
    """PostgreSQL не стал доступен до истечения заданного времени."""


def project_manual_delivery_retry(session_factory, project_id: int):
    """Собирает проверку права на повтор отправки в границах проекта."""
    from postify.application.delivery.manual_operations import ManualDeliveryRetry
    from postify.infrastructure.repositories.sqlalchemy_delivery import (
        SqlAlchemyDeliveryRepository,
    )

    return ManualDeliveryRetry(
        SqlAlchemyDeliveryRepository(session_factory, project_id)
    )


@contextmanager
def open_project_publish_once(
    settings: Settings,
    *,
    project_id: int,
    transport: httpx.BaseTransport | None = None,
    record_operation: bool = True,
    post_id: int | None = None,
    delivery_id: int | None = None,
):
    """Открывает публикацию из свежего графа проекта, без env-секретов.

    Канал берётся прямо из проекта: маршрутов «формат → канал» больше нет,
    проект равен одному каналу.
    """
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
        runtime_channel = graph.publication_channel()
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
        # Снимок канала переживает его правку: доставка должна помнить, куда
        # именно она уходила.
        channel_snapshot = {
            "id": channel.id,
            "name": channel.name,
            "provider": channel.provider,
            "configuration": dict(channel.configuration),
        }
        action = PublishContent(
            SqlAlchemyDeliveryRepository(
                sessions,
                project_id,
                channel_id=channel.id,
                channel_snapshot=channel_snapshot,
                post_id=post_id,
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
                SqlAlchemyOperationRunRepository(sessions, project_id),
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
