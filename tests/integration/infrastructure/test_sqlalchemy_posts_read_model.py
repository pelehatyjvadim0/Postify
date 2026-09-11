"""Read model для UI: посты, журнал операций, публикации.

Проверяется то, ради чего слой существует: фильтры списка, полнота карточки и
изоляция по проекту — чужой проект обязан отдавать пустоту либо LookupError.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from postify.infrastructure.repositories.sqlalchemy_dashboard import (
    EXCERPT_LIMIT,
    SqlAlchemyDashboardRepository,
)


pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 11, 9, tzinfo=UTC)


def _project(connection, project_id: int, name: str) -> None:
    # Проект принадлежит пользователю, поэтому владелец нужен и в фикстуре.
    connection.execute(
        text(
            "INSERT INTO users(id,telegram_user_id,telegram_username,display_name,"
            "created_at,is_active) VALUES (:id,:telegram_id,'','',:now,true)"
        ),
        {"id": project_id, "telegram_id": str(project_id), "now": NOW},
    )
    connection.execute(
        text(
            "INSERT INTO content_projects"
            " (id,owner_id,name,project_prompt,language,audience,timezone,configuration,"
            "created_at,updated_at)"
            " VALUES (:id,:id,:name,'Тема','ru','Аудитория','UTC','{}'::jsonb,:now,:now)"
        ),
        {"id": project_id, "name": name, "now": NOW},
    )
    connection.execute(
        text(
            "INSERT INTO channel_connections"
            " (id,project_id,provider,name,enabled,configuration,connection_status,created_at,updated_at)"
            " VALUES (:id,:project,'telegram',:name,true,'{}'::jsonb,'ok',:now,:now)"
        ),
        {"id": project_id, "project": project_id, "name": name, "now": NOW},
    )


def _post(
    connection,
    post_id: int,
    project_id: int,
    *,
    status: str,
    post_text: str = "Текст поста",
    media_path: str | None = None,
    media_deleted_at: datetime | None = None,
    scheduled_at: datetime | None = None,
    generation: str = "{}",
    created_at: datetime = NOW,
) -> None:
    connection.execute(
        text(
            "INSERT INTO posts"
            " (id,project_id,post_text,media_path,media_mime,media_deleted_at,status,"
            " scheduled_at,generation,created_at,updated_at)"
            " VALUES (:id,:project,:post_text,:media_path,:media_mime,"
            " :media_deleted_at,:status,:scheduled_at,CAST(:generation AS jsonb),:created_at,:created_at)"
        ),
        {
            "id": post_id,
            "project": project_id,
            "post_text": post_text,
            "media_path": media_path,
            "media_mime": None if media_path is None else "image/png",
            "media_deleted_at": media_deleted_at,
            "status": status,
            "scheduled_at": scheduled_at,
            "generation": generation,
            "created_at": created_at,
        },
    )


def _repository(database_url: str):
    engine = create_engine(database_url)
    return engine, SqlAlchemyDashboardRepository(sessionmaker(engine))


def test_posts_filter_by_status_and_shorten_text(migrated_database_url: str) -> None:
    long_text = "а" * (EXCERPT_LIMIT + 50)
    engine, repository = _repository(migrated_database_url)
    try:
        with engine.begin() as connection:
            _project(connection, 1, "Проект")
            _post(connection, 10, 1, status="needs_review", post_text=long_text,
                  media_path="/media/10.png", created_at=NOW)
            _post(connection, 11, 1, status="approved", created_at=NOW + timedelta(hours=1))

        review = repository.posts(1, status="needs_review")
        every = repository.posts(1)
    finally:
        engine.dispose()

    assert [item.post_id for item in every] == [11, 10]
    assert [item.post_id for item in review] == [10]
    summary = review[0]
    assert summary.id == summary.post_id == 10
    assert summary.excerpt == "а" * EXCERPT_LIMIT
    assert summary.char_count == EXCERPT_LIMIT + 50
    assert summary.media_available is True
    assert summary.delivery_status is None


def test_posts_report_media_and_delivery_state(migrated_database_url: str) -> None:
    engine, repository = _repository(migrated_database_url)
    try:
        with engine.begin() as connection:
            _project(connection, 1, "Проект")
            _post(connection, 10, 1, status="published", media_path="/media/10.png",
                  media_deleted_at=NOW)
            connection.execute(
                text(
                    "INSERT INTO deliveries"
                    " (id,project_id,post_id,channel_id,channel_snapshot,status,attempt_no,"
                    " message_id,sending_started_at,confirmed_at,created_at,updated_at)"
                    " VALUES (100,1,10,1,'{}'::jsonb,'published',1,555,:now,:now,:now,:now)"
                ),
                {"now": NOW},
            )

        summary = repository.posts(1)[0]
    finally:
        engine.dispose()

    # Медиа удалено после публикации — файла больше нет, флаг обязан упасть.
    assert summary.media_available is False
    assert summary.delivery_status == "published"


def test_post_detail_carries_history_generation_and_failure(migrated_database_url: str) -> None:
    engine, repository = _repository(migrated_database_url)
    try:
        with engine.begin() as connection:
            _project(connection, 1, "Проект")
            _post(
                connection, 10, 1, status="failed", post_text="Полный текст",
                media_path="/media/10.png", scheduled_at=NOW + timedelta(hours=2),
                generation='{"provider":"codex","model":"gpt-5.6-terra","iterations":2}',
            )
            for index, (status, reason) in enumerate(
                (("generating", None), ("needs_review", None), ("failed", "delivery_failed"))
            ):
                connection.execute(
                    text(
                        "INSERT INTO post_status_history"
                        " (project_id,post_id,status,reason,created_at)"
                        " VALUES (1,10,:status,:reason,:created_at)"
                    ),
                    {"status": status, "reason": reason,
                     "created_at": NOW + timedelta(minutes=index)},
                )
            connection.execute(
                text(
                    "INSERT INTO deliveries"
                    " (id,project_id,post_id,channel_id,channel_snapshot,status,attempt_no,"
                    " failure_code,failure_reason,sending_started_at,created_at,updated_at)"
                    " VALUES (100,1,10,1,'{}'::jsonb,'failed',3,'chat_not_found',"
                    " 'Канал недоступен',:now,:now,:now)"
                ),
                {"now": NOW},
            )

        detail = repository.post(1, 10)
        media = repository.post_media_path(1, 10)
    finally:
        engine.dispose()

    assert detail.post_text == "Полный текст"
    assert detail.char_count == len("Полный текст")
    assert detail.media_mime == "image/png"
    assert detail.generation["model"] == "gpt-5.6-terra"
    assert [entry.status for entry in detail.history] == [
        "generating", "needs_review", "failed",
    ]
    assert detail.history[-1].reason == "delivery_failed"
    assert detail.delivery_status == "failed"
    assert detail.failure_code == "chat_not_found"
    assert detail.failure_reason == "Канал недоступен"
    assert detail.published_at is None
    assert media == ("/media/10.png", "image/png")


def test_post_media_path_hides_deleted_media(migrated_database_url: str) -> None:
    engine, repository = _repository(migrated_database_url)
    try:
        with engine.begin() as connection:
            _project(connection, 1, "Проект")
            _post(connection, 10, 1, status="published", media_path="/media/10.png",
                  media_deleted_at=NOW)

        with pytest.raises(LookupError):
            repository.post_media_path(1, 10)
    finally:
        engine.dispose()


def test_operations_and_publications_are_readable(migrated_database_url: str) -> None:
    engine, repository = _repository(migrated_database_url)
    try:
        with engine.begin() as connection:
            _project(connection, 1, "Проект")
            _post(connection, 10, 1, status="published")
            connection.execute(
                text(
                    "INSERT INTO operation_runs"
                    " (id,project_id,operation,status,outcome,mode,actor,result,started_at,finished_at)"
                    " VALUES (500,1,'generate_post','succeeded','completed','manual','user',"
                    " CAST(:result AS jsonb),:started,:finished)"
                ),
                {"result": '{"post_id": 10}', "started": NOW,
                 "finished": NOW + timedelta(seconds=30)},
            )
            connection.execute(
                text(
                    "INSERT INTO operation_runs"
                    " (id,project_id,operation,status,started_at)"
                    " VALUES (501,1,'publish_once','running',:started)"
                ),
                {"started": NOW + timedelta(minutes=1)},
            )
            connection.execute(
                text(
                    "INSERT INTO deliveries"
                    " (id,project_id,post_id,channel_id,channel_snapshot,status,attempt_no,"
                    " message_id,sending_started_at,confirmed_at,created_at,updated_at)"
                    " VALUES (100,1,10,1,'{}'::jsonb,'published',2,555,:now,:confirmed,:now,:confirmed)"
                ),
                {"now": NOW, "confirmed": NOW + timedelta(seconds=5)},
            )
            for attempt_no, outcome, code in ((1, "retryable", "timeout"), (2, "published", None)):
                connection.execute(
                    text(
                        "INSERT INTO delivery_attempts"
                        " (project_id,delivery_id,attempt_no,outcome,code,reason,message_id,"
                        " started_at,finished_at)"
                        " VALUES (1,100,:attempt_no,:outcome,:code,NULL,NULL,:now,:now)"
                    ),
                    {"attempt_no": attempt_no, "outcome": outcome, "code": code, "now": NOW},
                )

        operations = repository.operations(1)
        single = repository.operation(1, 500)
        publications = repository.publications(1)
    finally:
        engine.dispose()

    assert [item.run_id for item in operations] == [501, 500]
    assert operations[0].status == "running"
    assert operations[0].duration is None
    assert single.operation == "generate_post"
    assert single.outcome == "completed"
    assert (single.mode, single.actor) == ("manual", "user")
    assert single.result["post_id"] == 10
    assert single.duration == timedelta(seconds=30)

    assert len(publications) == 1
    publication = publications[0]
    assert (publication.delivery_id, publication.post_id) == (100, 10)
    assert publication.provider == "telegram"
    assert publication.attempt_count == 2
    assert [attempt.outcome for attempt in publication.attempts] == ["retryable", "published"]
    assert publication.message_id == 555


def test_foreign_project_sees_nothing(migrated_database_url: str) -> None:
    engine, repository = _repository(migrated_database_url)
    try:
        with engine.begin() as connection:
            _project(connection, 1, "Свой")
            _project(connection, 2, "Чужой")
            _post(connection, 10, 1, status="needs_review", media_path="/media/10.png")
            connection.execute(
                text(
                    "INSERT INTO operation_runs"
                    " (id,project_id,operation,status,outcome,mode,actor,result,started_at,finished_at)"
                    " VALUES (500,1,'generate_post','succeeded','completed','manual','user',"
                    " '{}'::jsonb,:now,:now)"
                ),
                {"now": NOW},
            )
            connection.execute(
                text(
                    "INSERT INTO deliveries"
                    " (id,project_id,post_id,channel_id,channel_snapshot,status,attempt_no,"
                    " sending_started_at,created_at,updated_at)"
                    " VALUES (100,1,10,1,'{}'::jsonb,'sending',1,:now,:now,:now)"
                ),
                {"now": NOW},
            )

        assert repository.posts(2) == ()
        assert repository.operations(2) == ()
        assert repository.publications(2) == ()
        with pytest.raises(LookupError):
            repository.post(2, 10)
        with pytest.raises(LookupError):
            repository.post_media_path(2, 10)
        with pytest.raises(LookupError):
            repository.operation(2, 500)
    finally:
        engine.dispose()


def test_unknown_post_and_operation_raise_lookup_error(migrated_database_url: str) -> None:
    engine, repository = _repository(migrated_database_url)
    try:
        with engine.begin() as connection:
            _project(connection, 1, "Проект")

        with pytest.raises(LookupError):
            repository.post(1, 404)
        with pytest.raises(LookupError):
            repository.operation(1, 404)
    finally:
        engine.dispose()
