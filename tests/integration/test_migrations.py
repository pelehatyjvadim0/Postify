"""Проверки цепочки миграций.

Цепочка начинается заново с baseline: старый контур импорта материалов снесён
вместе с его девятнадцатью ревизиями. Поэтому здесь проверяется не история, а
инварианты схемы, на которые опирается код, и обратимость каждой ревизии.
"""

from __future__ import annotations

from datetime import UTC, datetime

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


pytestmark = pytest.mark.integration


BASELINE = "20260911_01"
USERS = "20260911_02"

BASELINE_TABLES = {
    "content_projects",
    "project_rubrics",
    "channel_connections",
    "posts",
    "post_status_history",
    "operation_runs",
    "deliveries",
    "delivery_attempts",
    "scheduled_jobs",
    "schedule_slot_claims",
}

USERS_TABLES = {"users", "user_sessions", "login_requests", "user_settings"}

REMOVED_TABLES = {
    "candidates",
    "content_attempts",
    "content_packages",
    "content_package_status_history",
    "content_package_media_versions",
    "source_connections",
    "telegram_source_state",
    "content_formats",
    "publication_routes",
}


def test_alembic_requires_dedicated_database_url(monkeypatch) -> None:
    monkeypatch.delenv("POSTIFY_ALEMBIC_DATABASE_URL", raising=False)

    config = Config("alembic.ini")

    try:
        command.upgrade(config, "head")
    except RuntimeError as error:
        assert "POSTIFY_ALEMBIC_DATABASE_URL" in str(error)
    else:
        raise AssertionError("Миграция не должна брать URL из другого источника")


def test_head_creates_the_whole_contour_and_nothing_from_the_old_one(
    alembic_config: Config, isolated_database_url: str
) -> None:
    command.upgrade(alembic_config, "head")

    engine = create_engine(isolated_database_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert BASELINE_TABLES | USERS_TABLES <= tables
    assert not REMOVED_TABLES & tables


def test_every_revision_is_reversible(
    alembic_config: Config, isolated_database_url: str
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, BASELINE)

    engine = create_engine(isolated_database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert not USERS_TABLES & tables
        assert BASELINE_TABLES <= tables
    finally:
        engine.dispose()

    command.downgrade(alembic_config, "base")

    engine = create_engine(isolated_database_url)
    try:
        remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
        assert remaining == set()
    finally:
        engine.dispose()

    command.upgrade(alembic_config, "head")


def test_vector_extension_is_available_for_the_media_pool(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Пул изображений ищет по эмбеддингам; расширение включает baseline, чтобы
    # образ БД и права проверились один раз, а не в середине работ.
    command.upgrade(alembic_config, "head")

    engine = create_engine(isolated_database_url)
    try:
        with engine.connect() as connection:
            installed = connection.execute(
                text("SELECT 1 FROM pg_extension WHERE extname='vector'")
            ).scalar_one_or_none()
    finally:
        engine.dispose()

    assert installed == 1


def test_project_equals_one_channel(
    alembic_config: Config, isolated_database_url: str
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(isolated_database_url)
    try:
        with engine.begin() as connection:
            _seed_project(connection)
            for name in ("Первый", "Второй"):
                connection.execute(
                    text(
                        "INSERT INTO channel_connections(project_id,provider,name,"
                        "enabled,configuration,connection_status,created_at,updated_at)"
                        " VALUES (1,'telegram',:name,true,'{}'::jsonb,'unconfigured',"
                        ":now,:now)"
                    ),
                    {"name": name, "now": datetime.now(UTC)},
                )
    except IntegrityError:
        pass
    else:
        raise AssertionError("Второй канал в проекте недопустим")
    finally:
        engine.dispose()


def test_post_status_vocabulary_is_enforced_by_the_database(
    alembic_config: Config, isolated_database_url: str
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(isolated_database_url)
    try:
        with engine.begin() as connection:
            _seed_project(connection)
            _insert_post(connection, "needs_review")
        with engine.begin() as connection:
            _insert_post(connection, "awaiting_review")
    except IntegrityError:
        pass
    else:
        raise AssertionError("Статус снесённого контура недопустим")
    finally:
        engine.dispose()


def test_operation_journal_keeps_its_vocabulary_and_single_running_run(
    alembic_config: Config, isolated_database_url: str
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(isolated_database_url)
    try:
        with engine.begin() as connection:
            _seed_project(connection)
            _start_operation(connection, "publish_once", mode="manual", actor="user")

        # Второй running той же операции в том же проекте запрещён частичным
        # уникальным индексом: пул операций UI опирается на это.
        with engine.begin() as connection:
            _start_operation(connection, "publish_once")
        raise AssertionError("Два running одной операции недопустимы")
    except IntegrityError:
        pass
    finally:
        engine.dispose()

    engine = create_engine(isolated_database_url)
    try:
        with engine.begin() as connection:
            _start_operation(connection, "run_once")
        raise AssertionError("Вид операции снесённого контура недопустим")
    except IntegrityError:
        pass
    finally:
        engine.dispose()


def test_failure_code_must_match_the_operation(
    alembic_config: Config, isolated_database_url: str
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(isolated_database_url)
    try:
        with engine.begin() as connection:
            _seed_project(connection)
            run_id = _start_operation(connection, "generate_post")
            connection.execute(
                text(
                    "UPDATE operation_runs SET status='failed',"
                    "failure_code='publish_once_failed',finished_at=:now"
                    " WHERE id=:id"
                ),
                {"id": run_id, "now": datetime.now(UTC)},
            )
        raise AssertionError("Чужой failure_code недопустим")
    except IntegrityError:
        pass
    finally:
        engine.dispose()


def test_project_requires_an_owner(
    alembic_config: Config, isolated_database_url: str
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(isolated_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO content_projects(id,name,topic,language,audience,"
                    "timezone,configuration,created_at,updated_at)"
                    " VALUES (1,'Проект','Тема','ru','Все','UTC','{}'::jsonb,:now,:now)"
                ),
                {"now": datetime.now(UTC)},
            )
        raise AssertionError("Проект без владельца недопустим")
    except IntegrityError:
        pass
    finally:
        engine.dispose()


def _seed_project(connection) -> None:
    now = datetime.now(UTC)
    connection.execute(
        text(
            "INSERT INTO users(id,telegram_user_id,telegram_username,display_name,"
            "created_at,is_active) VALUES (1,'101','','',:now,true)"
        ),
        {"now": now},
    )
    connection.execute(
        text(
            "INSERT INTO content_projects(id,owner_id,name,topic,language,audience,"
            "timezone,configuration,created_at,updated_at)"
            " VALUES (1,1,'Проект','Тема','ru','Все','UTC','{}'::jsonb,:now,:now)"
        ),
        {"now": now},
    )


def _insert_post(connection, status: str) -> None:
    now = datetime.now(UTC)
    connection.execute(
        text(
            "INSERT INTO posts(project_id,post_text,status,created_at,updated_at)"
            " VALUES (1,'Текст',:status,:now,:now)"
        ),
        {"status": status, "now": now},
    )


def _start_operation(
    connection, operation: str, *, mode: str = "automatic", actor: str = "scheduler"
) -> int:
    return connection.execute(
        text(
            "INSERT INTO operation_runs(project_id,operation,status,mode,actor,started_at)"
            " VALUES (1,:operation,'running',:mode,:actor,:now) RETURNING id"
        ),
        {
            "operation": operation,
            "mode": mode,
            "actor": actor,
            "now": datetime.now(UTC),
        },
    ).scalar_one()
