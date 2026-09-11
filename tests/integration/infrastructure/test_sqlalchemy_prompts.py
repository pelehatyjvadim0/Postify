"""Хранилище промптов на настоящей PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from postify.infrastructure.repositories.sqlalchemy_prompts import (
    SqlAlchemyPromptRepository,
)


pytestmark = pytest.mark.integration


NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)


@pytest.fixture
def engine(migrated_database_url: str):
    engine = create_engine(migrated_database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def repository(engine):
    return SqlAlchemyPromptRepository(sessionmaker(engine, expire_on_commit=False))


def make_user(engine, user_id: int) -> int:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users(id,telegram_user_id,telegram_username,"
                "display_name,created_at,is_active)"
                " VALUES (:id,:telegram,'user','Пользователь',:now,true)"
            ),
            {"id": user_id, "telegram": str(100 + user_id), "now": NOW},
        )
    return user_id


def test_system_prompt_is_empty_until_it_is_set(repository) -> None:
    assert repository.system_prompt() == ""


def test_system_prompt_is_replaced_whole(repository) -> None:
    repository.set_system_prompt("Ты SMM-специалист.", now=NOW)
    repository.set_system_prompt("Ты редактор канала.", now=LATER)

    assert repository.system_prompt() == "Ты редактор канала."


def test_system_prompt_keeps_its_formatting(repository) -> None:
    # Промпт многострочный: схлопнутый в строку он теряет структуру инструкций.
    prompt = "Правила:\n- без эмодзи\n- до 900 знаков"

    repository.set_system_prompt(prompt, now=NOW)

    assert repository.system_prompt() == prompt


def test_settings_table_holds_exactly_one_row(engine) -> None:
    # Поломка: появляется вторая строка настроек, и сервер работает с тем
    # промптом, который случайно вернулся первым.
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO app_settings(id,system_prompt,updated_at)"
                    " VALUES (2,'Второй промпт',:now)"
                ),
                {"now": NOW},
            )


def test_common_prompt_row_appears_on_the_first_write(repository, engine) -> None:
    first = make_user(engine, 1)
    assert repository.common_prompt(first) == ""

    repository.set_common_prompt(first, "Пиши без канцелярита.", now=NOW)

    assert repository.common_prompt(first) == "Пиши без канцелярита."


def test_common_prompt_is_isolated_between_users(repository, engine) -> None:
    first = make_user(engine, 1)
    second = make_user(engine, 2)

    repository.set_common_prompt(first, "Мой стиль", now=NOW)
    repository.set_common_prompt(second, "Чужой стиль", now=NOW)
    repository.set_common_prompt(first, "Мой стиль, второй раз", now=LATER)

    assert repository.common_prompt(first) == "Мой стиль, второй раз"
    assert repository.common_prompt(second) == "Чужой стиль"


def test_common_prompt_of_unknown_user_is_empty(repository) -> None:
    assert repository.common_prompt(404) == ""


def test_project_prompt_replaced_the_old_topic_column(engine) -> None:
    # Третий уровень промптов хранится в самом проекте: отдельной колонки нет.
    columns = {
        column["name"] for column in inspect(engine).get_columns("content_projects")
    }

    assert "project_prompt" in columns
    assert "topic" not in columns
