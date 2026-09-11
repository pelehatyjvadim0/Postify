from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from postify.infrastructure.repositories.sqlalchemy_schedule import (
    SqlAlchemyScheduleRepository,
)


pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


def _seed(engine, *, status: str, scheduled_at: datetime | None, channel: bool = True) -> int:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users(id,telegram_user_id,telegram_username,display_name,"
                "created_at,is_active) VALUES (1,'101','','',:now,true)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO content_projects(id,owner_id,name,project_prompt,language,audience,"
                "timezone,configuration,created_at,updated_at)"
                " VALUES (1,1,'Агротех','Тема','ru','Все','Europe/Moscow','{}'::jsonb,"
                ":now,:now)"
            ),
            {"now": NOW},
        )
        if channel:
            connection.execute(
                text(
                    "INSERT INTO channel_connections(id,project_id,provider,name,enabled,"
                    "configuration,connection_status,created_at,updated_at)"
                    " VALUES (1,1,'telegram','@agrotech',true,'{}'::jsonb,'ok',:now,:now)"
                ),
                {"now": NOW},
            )
        post_id = connection.execute(
            text(
                "INSERT INTO posts(project_id,post_text,status,scheduled_at,"
                "created_at,updated_at)"
                " VALUES (1,'Текст',:status,:scheduled_at,:now,:now) RETURNING id"
            ),
            {"status": status, "scheduled_at": scheduled_at, "now": NOW},
        ).scalar_one()
        if scheduled_at is not None:
            connection.execute(
                text(
                    "INSERT INTO content_plan_slots"
                    "(project_id,publish_at,generate_at,topic,status,post_id,created_at,updated_at)"
                    " VALUES (1,:at,:at,'Тема','planned',:post,:now,:now)"
                ),
                {"post": post_id, "at": scheduled_at, "now": NOW},
            )
        return post_id


def _repository(engine) -> SqlAlchemyScheduleRepository:
    return SqlAlchemyScheduleRepository(sessionmaker(engine))


def test_schedule_lists_every_project_with_its_timezone(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    try:
        _seed(engine, status="approved", scheduled_at=NOW - timedelta(minutes=1))

        schedules = _repository(engine).list_schedules()
    finally:
        engine.dispose()

    assert [(item.project_id, item.timezone) for item in schedules] == [
        (1, "Europe/Moscow")
    ]


def test_due_approved_post_becomes_a_publish_command(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    try:
        post_id = _seed(engine, status="approved", scheduled_at=NOW - timedelta(minutes=1))

        commands = _repository(engine).due_publications(project_id=1, now=NOW)
    finally:
        engine.dispose()

    assert [(item.kind, item.post_id) for item in commands] == [("publish_once", post_id)]


def test_publication_time_comes_from_linked_plan_slot(
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    slot_time = NOW - timedelta(minutes=1)
    try:
        post_id = _seed(
            engine, status="approved", scheduled_at=NOW + timedelta(hours=1)
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE content_plan_slots SET publish_at=:at,generate_at=:at "
                    "WHERE post_id=:post"
                ),
                {"at": slot_time, "post": post_id},
            )

        commands = _repository(engine).due_publications(project_id=1, now=NOW)
    finally:
        engine.dispose()

    assert len(commands) == 1
    assert commands[0].post_id == post_id
    assert commands[0].scheduled_for == slot_time


def test_approved_post_without_plan_slot_is_not_scheduled(
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    try:
        post_id = _seed(engine, status="approved", scheduled_at=None)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE posts SET scheduled_at=:at WHERE id=:post"),
                {"at": NOW - timedelta(minutes=1), "post": post_id},
            )

        assert _repository(engine).due_publications(project_id=1, now=NOW) == ()
    finally:
        engine.dispose()


def test_post_without_channel_or_time_is_not_due(migrated_database_url: str) -> None:
    # Поломка: планировщик берёт пост, который отправить некуда, и жжёт попытки.
    engine = create_engine(migrated_database_url)
    try:
        _seed(
            engine,
            status="approved",
            scheduled_at=NOW - timedelta(minutes=1),
            channel=False,
        )

        assert _repository(engine).due_publications(project_id=1, now=NOW) == ()
    finally:
        engine.dispose()


def test_future_and_unapproved_posts_wait(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    try:
        _seed(engine, status="approved", scheduled_at=NOW + timedelta(hours=1))
        with create_engine(migrated_database_url).begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO posts(project_id,post_text,status,scheduled_at,"
                    "created_at,updated_at)"
                    " VALUES (1,'Ещё на ревью','needs_review',:past,:now,:now)"
                ),
                {"past": NOW - timedelta(hours=1), "now": NOW},
            )

        assert _repository(engine).due_publications(project_id=1, now=NOW) == ()
    finally:
        engine.dispose()


def test_accepted_command_claims_the_slot_once(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    try:
        _seed(engine, status="approved", scheduled_at=NOW - timedelta(minutes=1))
        repository = _repository(engine)
        command = repository.due_publications(project_id=1, now=NOW)[0]

        accepted = repository.accept(command)
        repeated = repository.accept(command)
    finally:
        engine.dispose()

    assert accepted is not None
    assert accepted.operation_run_id is not None and accepted.job_id is not None
    # Тот же слот второй раз не занимается: иначе один пост уйдёт дважды.
    assert repeated is None
