from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from alembic import command
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from postify.infrastructure.repositories.sqlalchemy_projects import (
    SqlAlchemyProjectRepository,
)
from postify.infrastructure.security.secrets import SecretCipher
from postify.adapters.channels.registry import ChannelProviderRegistry
from postify.adapters.sources.registry import SourceProviderRegistry
from postify.application.projects.bootstrap_project import BootstrapProject
from tests.unit.application.projects.test_bootstrap_project import settings
from tests.unit.domain.projects.test_models import configuration


pytestmark = pytest.mark.integration


def test_project_repository_updates_identity_without_losing_configuration(
    alembic_config, isolated_database_url
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(isolated_database_url)
    repository = SqlAlchemyProjectRepository(sessionmaker(engine))
    now = datetime(2026, 8, 12, 9, tzinfo=UTC)
    try:
        repository.replace_default(
            name="Технологии просто",
            topic="Практичная автоматизация",
            language="ru",
            audience="Продуктовые команды",
            timezone="Europe/Moscow",
            configuration=configuration(),
            now=now,
        )
        project = repository.get(1)
        repository.save(
            type(project)(
                project.id,
                "Новая редакция",
                project.topic,
                project.language,
                project.audience,
                project.timezone,
                project.configuration,
                project.created_at,
                datetime(2026, 8, 12, 10, tzinfo=UTC),
            )
        )

        updated = repository.get(1)
        assert updated.name == "Новая редакция"
        assert updated.configuration == configuration()
    finally:
        engine.dispose()


def test_project_repository_does_not_return_another_project(
    alembic_config, isolated_database_url
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(isolated_database_url)
    repository = SqlAlchemyProjectRepository(sessionmaker(engine))
    try:
        with pytest.raises(LookupError):
            repository.get(999)
    finally:
        engine.dispose()


def test_bootstrap_repository_creates_full_graph_once(
    alembic_config, isolated_database_url
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(isolated_database_url)
    repository = SqlAlchemyProjectRepository(sessionmaker(engine))
    action = BootstrapProject(
        repository,
        SourceProviderRegistry(),
        ChannelProviderRegistry(),
        cipher=None,
        clock=lambda: datetime(2026, 8, 12, 9, tzinfo=UTC),
    )
    try:
        assert repository.active_project() is None
        first = action.execute(settings(), telegram=None)
        second = action.execute(settings(), telegram=None)

        assert first.id == second.id == 1
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT count(*) FROM source_connections"
            ).scalar_one() == 1
            assert connection.exec_driver_sql(
                "SELECT count(*) FROM content_formats"
            ).scalar_one() == 1
            assert connection.exec_driver_sql(
                "SELECT count(*) FROM calls_to_action"
            ).scalar_one() == 1
    finally:
        engine.dispose()


def test_repository_removes_only_channel_secret_and_keeps_connection(
    alembic_config, isolated_database_url
) -> None:
    # Break caught: explicit credential removal deletes the channel or leaves encrypted material readable.
    command.upgrade(alembic_config, "head")
    engine = create_engine(isolated_database_url)
    repository = SqlAlchemyProjectRepository(sessionmaker(engine))
    cipher = SecretCipher(Fernet.generate_key().decode())
    telegram = SimpleNamespace(
        telegram_chat_id="-100123",
        telegram_bot_token=SecretStr("123:token"),
    )
    try:
        BootstrapProject(
            repository,
            SourceProviderRegistry(),
            ChannelProviderRegistry(),
            cipher=cipher,
            clock=lambda: datetime(2026, 8, 12, 9, tzinfo=UTC),
        ).execute(settings(), telegram)

        result = repository.remove_channel_secret(
            1, 1, datetime(2026, 8, 12, 10, tzinfo=UTC)
        )
        stored = repository.get_resource(1, "channels", 1)

        assert result["secretConfigured"] is False
        assert result["connection_status"] == "unconfigured"
        assert stored["encrypted_secret"] is None
        assert stored["configuration"] == {"chat_id": "-100123"}
    finally:
        engine.dispose()


def test_schedule_transaction_rolls_back_every_change_when_commit_fails(
    alembic_config, isolated_database_url
) -> None:
    # Break caught: ingestion schedule commits before publication schedule failure and leaves a partially saved section.
    command.upgrade(alembic_config, "head")
    engine = create_engine(isolated_database_url)
    normal = SqlAlchemyProjectRepository(sessionmaker(engine))
    cipher = SecretCipher(Fernet.generate_key().decode())
    telegram = SimpleNamespace(
        telegram_chat_id="-100123",
        telegram_bot_token=SecretStr("123:token"),
    )

    class FailingCommitSession(Session):
        def commit(self) -> None:
            self.flush()
            raise RuntimeError("forced commit failure")

    try:
        BootstrapProject(
            normal,
            SourceProviderRegistry(),
            ChannelProviderRegistry(),
            cipher=cipher,
            clock=lambda: datetime(2026, 8, 12, 9, tzinfo=UTC),
        ).execute(settings(), telegram)
        failing = SqlAlchemyProjectRepository(
            sessionmaker(engine, class_=FailingCommitSession)
        )

        with pytest.raises(RuntimeError, match="forced commit failure"):
            failing.update_schedules(
                1,
                ({"id": 1, "schedule": "0 8 * * *"},),
                ({"id": 1, "autopublish": False, "slots": ("08:30", "13:30", "18:30")},),
                datetime(2026, 8, 12, 10, tzinfo=UTC),
            )

        assert normal.get_resource(1, "sources", 1)["schedule"] == "0 7 * * 1-5"
        assert normal.get_resource(1, "routes", 1)["schedule"] == {
            "autopublish": True,
            "slots": ["09:00", "14:00", "19:00"],
        }
    finally:
        engine.dispose()
