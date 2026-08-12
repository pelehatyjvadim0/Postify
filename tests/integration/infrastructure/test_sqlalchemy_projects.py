from datetime import UTC, datetime

import pytest
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from postify.infrastructure.repositories.sqlalchemy_projects import (
    SqlAlchemyProjectRepository,
)
from postify.adapters.channels.registry import ChannelProviderRegistry
from postify.adapters.sources.registry import SourceProviderRegistry
from postify.application.projects.bootstrap_project import BootstrapProject
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
    from tests.unit.application.projects.test_bootstrap_project import settings

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
