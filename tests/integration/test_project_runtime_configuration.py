from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from postify.application.projects.manage_channel import SetProjectChannel
from postify.application.projects.manage_project import ManageProject
from postify.application.projects.manage_rubrics import ManageRubrics
from postify.infrastructure.repositories.sqlalchemy_projects import (
    SqlAlchemyProjectRepository,
)
from postify.infrastructure.security.secrets import SecretCipher


pytestmark = pytest.mark.integration


NOW = datetime(2026, 9, 11, 9, tzinfo=UTC)


def test_runtime_graph_gives_pipeline_enabled_rubrics_and_project_channel(
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    repository = SqlAlchemyProjectRepository(sessionmaker(engine, expire_on_commit=False))
    cipher = SecretCipher(Fernet.generate_key().decode("ascii"))
    try:
        owner_id = _owner(engine)
        project = ManageProject(repository, clock=lambda: NOW).create(
            {"name": "Агротех", "timezone": "Europe/Moscow"}, owner_id=owner_id
        )
        rubrics = ManageRubrics(repository, clock=lambda: NOW)
        rubrics.create(project.id, {"name": "Кейс", "instructions": "Разбор задачи"})
        disabled = rubrics.create(
            project.id, {"name": "Анонс", "instructions": "Коротко", "enabled": False}
        )
        SetProjectChannel(repository, cipher, clock=lambda: NOW).execute(
            project.id, bot_token="123:secret", chat_id="@agrotech"
        )

        graph = repository.runtime_graph(project.id)
    finally:
        engine.dispose()

    assert graph.project.name == "Агротех"
    assert [item.name for item in graph.enabled_rubrics()] == ["Кейс"]
    assert disabled.id not in {item.id for item in graph.enabled_rubrics()}
    channel = graph.publication_channel()
    assert channel.connection.configuration == {"chat_id": "@agrotech"}
    assert cipher.decrypt(channel.encrypted_secret) == "123:secret"


def test_runtime_graph_without_channel_refuses_to_publish(
    migrated_database_url: str,
) -> None:
    # Поломка: конвейер доходит до отправки и падает уже после генерации поста.
    engine = create_engine(migrated_database_url)
    repository = SqlAlchemyProjectRepository(sessionmaker(engine, expire_on_commit=False))
    try:
        project = ManageProject(repository, clock=lambda: NOW).create(
            {"name": "Без канала", "timezone": "UTC"}, owner_id=_owner(engine)
        )
        graph = repository.runtime_graph(project.id)
    finally:
        engine.dispose()

    assert graph.channel is None
    with pytest.raises(RuntimeError, match="publication_channel_unavailable"):
        graph.publication_channel()


def _owner(engine) -> int:
    """Проект принадлежит пользователю, поэтому владелец нужен и в фикстуре."""
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO users(telegram_user_id,telegram_username,display_name,"
                "created_at,is_active) VALUES ('101','','',:now,true) RETURNING id"
            ),
            {"now": NOW},
        ).scalar_one()
