from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from postify.application.projects.check_channel import CheckChannel
from postify.application.projects.manage_channel import (
    RemoveProjectChannel,
    SetProjectChannel,
)
from postify.application.projects.manage_project import ManageProject
from postify.application.projects.manage_rubrics import ManageRubrics
from postify.infrastructure.repositories.sqlalchemy_projects import (
    SqlAlchemyProjectRepository,
)
from postify.infrastructure.security.secrets import SecretCipher


pytestmark = pytest.mark.integration


OWNER_ID = 101
NOW = datetime(2026, 9, 11, 9, tzinfo=UTC)
LATER = datetime(2026, 9, 11, 10, tzinfo=UTC)


@pytest.fixture
def repository(migrated_database_url: str):
    engine = create_engine(migrated_database_url)
    try:
        # Проект принадлежит пользователю, поэтому владелец нужен даже тестам.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users(id,telegram_user_id,telegram_username,"
                    "display_name,created_at,is_active)"
                    " VALUES (:id,:telegram_id,'','',:now,true)"
                ),
                {"id": OWNER_ID, "telegram_id": str(OWNER_ID), "now": NOW},
            )
        yield SqlAlchemyProjectRepository(sessionmaker(engine, expire_on_commit=False))
    finally:
        engine.dispose()


def cipher() -> SecretCipher:
    return SecretCipher(Fernet.generate_key().decode("ascii"))


def make_project(repository, name: str = "Агротех", timezone: str = "Europe/Moscow"):
    return ManageProject(repository, clock=lambda: NOW).create(
        {"name": name, "timezone": timezone}, owner_id=OWNER_ID
    )


def test_project_update_keeps_configuration_and_bumps_timestamp(repository) -> None:
    project = make_project(repository)

    ManageProject(repository, clock=lambda: LATER).update(
        project.id, {"name": "Новая редакция", "tone": "Дружелюбный"}
    )
    stored = repository.get(project.id)

    assert stored.name == "Новая редакция"
    assert stored.configuration.tone == "Дружелюбный"
    assert stored.configuration.media_max_bytes == project.configuration.media_max_bytes
    assert stored.updated_at == LATER


def test_unknown_project_is_not_readable(repository) -> None:
    with pytest.raises(LookupError):
        repository.get(999)


def test_rubrics_of_another_project_are_invisible_and_unchangeable(repository) -> None:
    # Поломка: rubric_id без фильтра по проекту выдаёт и правит чужие рубрики.
    mine = make_project(repository, name="Мой проект")
    other = make_project(repository, name="Чужой проект")
    rubrics = ManageRubrics(repository, clock=lambda: NOW)
    stranger = rubrics.create(other.id, {"name": "Чужая", "instructions": "Секрет"})

    assert rubrics.list(mine.id) == ()
    with pytest.raises(LookupError):
        rubrics.update(mine.id, stranger.id, {"enabled": False})
    with pytest.raises(LookupError):
        repository.update_rubric(mine.id, stranger.id, values={"enabled": False}, now=LATER)
    with pytest.raises(LookupError):
        repository.delete_rubric(mine.id, stranger.id)
    assert rubrics.list(other.id)[0].instructions == "Секрет"


def test_rubric_lifecycle_persists_partial_update(repository) -> None:
    project = make_project(repository)
    rubrics = ManageRubrics(repository, clock=lambda: NOW)
    created = rubrics.create(project.id, {"name": "Кейс", "instructions": "Разбор задачи"})

    rubrics.update(project.id, created.id, {"instructions": "Разбор задачи клиента"})
    stored = rubrics.list(project.id)

    assert [(item.name, item.instructions, item.enabled) for item in stored] == [
        ("Кейс", "Разбор задачи клиента", True)
    ]

    rubrics.delete(project.id, created.id)
    assert rubrics.list(project.id) == ()


def test_rubric_names_are_unique_inside_one_project(repository) -> None:
    project = make_project(repository)
    rubrics = ManageRubrics(repository, clock=lambda: NOW)
    rubrics.create(project.id, {"name": "Кейс", "instructions": "Разбор"})

    with pytest.raises(IntegrityError):
        rubrics.create(project.id, {"name": "Кейс", "instructions": "Другое"})


def test_channel_is_single_per_project_and_hides_its_token(repository) -> None:
    # Поломка: повторное подключение плодит вторую запись канала или светит токен.
    project = make_project(repository)
    secrets = cipher()
    action = SetProjectChannel(repository, secrets, clock=lambda: NOW)

    action.execute(project.id, bot_token="123:first", chat_id="@first")
    view = action.execute(project.id, bot_token="123:second", chat_id="@second")

    connection, encrypted_secret = repository.get_channel(project.id)
    assert view == {"configured": True, "chat_id": "@second", "status": "configured"}
    assert connection.secret_configured is True
    assert "second" not in encrypted_secret
    assert secrets.decrypt(encrypted_secret) == "123:second"
    assert connection.configuration == {"chat_id": "@second"}


def test_channel_check_stores_observed_status(repository) -> None:
    project = make_project(repository)
    secrets = cipher()
    SetProjectChannel(repository, secrets, clock=lambda: NOW).execute(
        project.id, bot_token="123:secret", chat_id="@agrotech"
    )

    class Checker:
        last_reason = "Добавьте бота администратором Telegram-канала."

        def check(self, configuration, secret):
            assert configuration == {"chat_id": "@agrotech"}
            assert secret == "123:secret"
            return "failed"

    result = CheckChannel(repository, secrets, Checker(), clock=lambda: LATER).execute(
        project.id
    )
    connection, _ = repository.get_channel(project.id)

    assert result["status"] == "failed"
    assert connection.connection_status == "failed"


def test_channel_of_another_project_is_not_reachable(repository) -> None:
    mine = make_project(repository, name="Мой проект")
    other = make_project(repository, name="Чужой проект")
    SetProjectChannel(repository, cipher(), clock=lambda: NOW).execute(
        other.id, bot_token="123:secret", chat_id="@other"
    )

    assert repository.get_channel(mine.id) is None
    with pytest.raises(LookupError):
        CheckChannel(repository, cipher(), object(), clock=lambda: LATER).execute(mine.id)
    with pytest.raises(LookupError):
        repository.set_channel_status(mine.id, "ok", LATER)
    RemoveProjectChannel(repository).execute(mine.id)
    assert repository.get_channel(other.id) is not None


def test_channel_removal_is_blocked_while_delivery_is_in_flight(repository) -> None:
    # Поломка: канал уходит вместе с секретом, а отправка остаётся без токена.
    project = make_project(repository)
    SetProjectChannel(repository, cipher(), clock=lambda: NOW).execute(
        project.id, bot_token="123:secret", chat_id="@agrotech"
    )
    connection, _ = repository.get_channel(project.id)
    with repository._session_factory() as session:
        session.execute(
            text(
                "INSERT INTO posts (project_id, post_text, status, generation,"
                " created_at, updated_at) VALUES (:project, 'Текст', 'approved',"
                " '{}'::jsonb, :now, :now)"
            ),
            {"project": project.id, "now": NOW},
        )
        post_id = session.execute(
            text("SELECT id FROM posts WHERE project_id=:project"),
            {"project": project.id},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO deliveries (project_id, post_id, channel_id, status,"
                " attempt_no, sending_started_at, created_at, updated_at)"
                " VALUES (:project, :post, :channel, 'sending', 1, :now, :now, :now)"
            ),
            {
                "project": project.id,
                "post": post_id,
                "channel": connection.id,
                "now": NOW,
            },
        )
        session.commit()

    with pytest.raises(RuntimeError, match="channel_delivery_in_flight"):
        RemoveProjectChannel(repository).execute(project.id)

    assert repository.get_channel(project.id) is not None


def test_project_delete_removes_its_rubrics_and_channel(repository) -> None:
    project = make_project(repository)
    ManageRubrics(repository, clock=lambda: NOW).create(
        project.id, {"name": "Кейс", "instructions": "Разбор"}
    )
    SetProjectChannel(repository, cipher(), clock=lambda: NOW).execute(
        project.id, bot_token="123:secret", chat_id="@agrotech"
    )

    ManageRubrics(repository, clock=lambda: NOW).delete(project.id, repository.list_rubrics(project.id)[0].id)
    RemoveProjectChannel(repository).execute(project.id)
    ManageProject(repository, clock=lambda: LATER).delete(project.id)

    with pytest.raises(LookupError):
        repository.get(project.id)
