from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


NOW = datetime(2026, 8, 12, 10, tzinfo=UTC)
DAY = date(2026, 8, 12)
DAY_START = datetime(2026, 8, 11, 21, tzinfo=UTC)
DAY_END = datetime(2026, 8, 12, 21, tzinfo=UTC)


def _repository(engine, project_id: int):
    from postify.infrastructure.repositories.sqlalchemy_dashboard import (
        SqlAlchemyDashboardRepository,
    )

    return SqlAlchemyDashboardRepository(sessionmaker(engine))


def _other_project(connection) -> int:
    return connection.execute(
        text(
            """INSERT INTO content_projects
            (id,name,topic,language,audience,timezone,configuration,created_at,updated_at)
            VALUES (2,'Другой','Другая тема','ru','Другая аудитория','Europe/Moscow',
                    '{}'::jsonb,:now,:now) RETURNING id"""
        ),
        {"now": NOW},
    ).scalar_one()


def _candidate(connection, project_id: int, marker: str) -> int:
    return connection.execute(
        text(
            """INSERT INTO candidates
            (project_id,source_name,source_id,title,url,discovered_at,raw_payload)
            VALUES (:project,'hn',:marker,:marker,:url,:now,'{}'::jsonb) RETURNING id"""
        ),
        {
            "project": project_id,
            "marker": marker,
            "url": f"https://source.test/{marker}",
            "now": NOW,
        },
    ).scalar_one()


def _decision(connection, project_id: int, candidate_id: int) -> None:
    connection.execute(
        text(
            """INSERT INTO candidate_decisions
            (project_id,candidate_id,status,reason,explanation,signals,policy_version,decided_at)
            VALUES (:project,:candidate,'selected','relevant','Объяснение',
                    '{"topic": "ai"}'::jsonb,'v1',:now)"""
        ),
        {"project": project_id, "candidate": candidate_id, "now": NOW},
    )


def _package(
    connection,
    project_id: int,
    candidate_id: int,
    marker: str,
    *,
    status: str = "approved",
) -> int:
    attempt_id = connection.execute(
        text(
            """INSERT INTO content_attempts
            (project_id,candidate_id,attempt_no,tier,status,source_url,started_at)
            VALUES (:project,:candidate,1,'fresh','packaged',:url,:now) RETURNING id"""
        ),
        {
            "project": project_id,
            "candidate": candidate_id,
            "url": f"https://source.test/{marker}",
            "now": NOW,
        },
    ).scalar_one()
    package_id = connection.execute(
        text(
            """INSERT INTO content_packages
            (project_id,attempt_id,source_url,context,analysis,post_text,media_path,
             media_mime,media_source_type,media_source_url,review_required,status,
             generation_snapshot,created_at,updated_at)
            VALUES (:project,:attempt,:url,'Контекст','Анализ','Полный текст поста',
                    '/media/post.jpg','image/jpeg','wikimedia','https://media.test/post.jpg',
                    false,:status,CAST(:snapshot AS jsonb),:now,:now) RETURNING id"""
        ),
        {
            "project": project_id,
            "attempt": attempt_id,
            "url": f"https://source.test/{marker}",
            "status": status,
            "snapshot": json.dumps({"format": "practical", "marker": marker}),
            "now": NOW,
        },
    ).scalar_one()
    connection.execute(
        text(
            """INSERT INTO content_package_status_history
            (project_id,package_id,status,reason,created_at)
            VALUES (:project,:package,:status,'approved_by_editor',:now)"""
        ),
        {"project": project_id, "package": package_id, "status": status, "now": NOW},
    )
    return package_id


def _route(connection, project_id: int) -> tuple[int, int]:
    format_id = connection.execute(
        text(
            """INSERT INTO content_formats
            (project_id,name,kind,instructions,enabled,created_at,updated_at)
            VALUES (:project,'Пост','text','Инструкция',true,:now,:now) RETURNING id"""
        ),
        {"project": project_id, "now": NOW},
    ).scalar_one()
    channel_id = connection.execute(
        text(
            """INSERT INTO channel_connections
            (project_id,provider,name,enabled,configuration,connection_status,created_at,updated_at)
            VALUES (:project,'telegram','Канал',true,'{}'::jsonb,'configured',:now,:now)
            RETURNING id"""
        ),
        {"project": project_id, "now": NOW},
    ).scalar_one()
    route_id = connection.execute(
        text(
            """INSERT INTO publication_routes
            (project_id,format_id,channel_id,enabled,schedule,created_at,updated_at)
            VALUES (:project,:format,:channel,true,CAST(:schedule AS jsonb),:now,:now)
            RETURNING id"""
        ),
        {
            "project": project_id,
            "format": format_id,
            "channel": channel_id,
            "schedule": json.dumps({"slots": ["09:00", "14:00", "19:00"]}),
            "now": NOW,
        },
    ).scalar_one()
    return route_id, channel_id


def test_materials_are_project_scoped_and_do_not_invent_score(
    migrated_database_url: str,
) -> None:
    # Поломка: чужие материалы попадают в UI или read model возвращает выдуманный score.
    engine = create_engine(migrated_database_url)
    try:
        with engine.begin() as connection:
            candidate = _candidate(connection, 1, "own")
            _decision(connection, 1, candidate)
            other = _other_project(connection)
            other_candidate = _candidate(connection, other, "foreign")
            _decision(connection, other, other_candidate)

        materials = _repository(engine, 1).materials(1)

        assert [item.title for item in materials] == ["own"]
        assert materials[0].decision_signals["topic"] == "ai"
        assert not hasattr(materials[0], "score")
    finally:
        engine.dispose()


def test_package_lookup_rejects_foreign_project_package(
    migrated_database_url: str,
) -> None:
    # Поломка: ID пакета обходит project isolation.
    engine = create_engine(migrated_database_url)
    try:
        with engine.begin() as connection:
            other = _other_project(connection)
            candidate = _candidate(connection, other, "foreign-package")
            foreign_package = _package(connection, other, candidate, "foreign-package")

        with pytest.raises(LookupError):
            _repository(engine, 1).package(1, foreign_package)
    finally:
        engine.dispose()


def test_queue_marks_approved_package_as_forecast_without_delivery(
    migrated_database_url: str,
) -> None:
    # Поломка: прогнозный слот показывается как сохранённая доставка.
    engine = create_engine(migrated_database_url)
    try:
        with engine.begin() as connection:
            candidate = _candidate(connection, 1, "forecast")
            package_id = _package(connection, 1, candidate, "forecast")
            _route(connection, 1)

        slots = _repository(engine, 1).queue(1, DAY)

        assert [slot.assignment_kind for slot in slots] == [
            "forecast",
            "empty",
            "empty",
        ]
        assert slots[0].package_id == package_id
        assert slots[0].delivery_id is None
    finally:
        engine.dispose()


def test_queue_confirms_legacy_delivery_created_by_delivery_repository(
    migrated_database_url: str,
) -> None:
    # Поломка: production delivery без route_id не видна в confirmed slot единственного route.
    from postify.infrastructure.repositories.sqlalchemy_delivery import (
        SqlAlchemyDeliveryRepository,
    )

    engine = create_engine(migrated_database_url)
    try:
        with engine.begin() as connection:
            candidate = _candidate(connection, 1, "legacy-confirmed")
            package_id = _package(connection, 1, candidate, "legacy-confirmed")
            _route(connection, 1)

        delivery_repository = SqlAlchemyDeliveryRepository(sessionmaker(engine))
        claim = delivery_repository.reserve_next(now=NOW - timedelta(minutes=2))
        assert claim is not None
        assert claim.package_id == package_id
        delivery_repository.confirm_published(claim, message_id=42, now=NOW)

        slots = _repository(engine, 1).queue(1, DAY)

        assert slots[0].assignment_kind == "confirmed"
        assert slots[0].package_id == package_id
        assert slots[0].delivery_id == claim.delivery_id
    finally:
        engine.dispose()


def test_dashboard_reads_persisted_package_publication_and_operation_fields(
    migrated_database_url: str,
) -> None:
    # Поломка: detail/publication/operation теряют реальные сохранённые поля.
    engine = create_engine(migrated_database_url)
    try:
        with engine.begin() as connection:
            candidate = _candidate(connection, 1, "published")
            _decision(connection, 1, candidate)
            package_id = _package(
                connection, 1, candidate, "published", status="published"
            )
            route_id, channel_id = _route(connection, 1)
            delivery_id = connection.execute(
                text(
                    """INSERT INTO deliveries
                    (project_id,package_id,route_id,channel_id,channel_snapshot,status,attempt_no,
                     message_id,sending_started_at,confirmed_at,created_at,updated_at)
                    VALUES (1,:package,:route,:channel,'{"provider": "telegram"}'::jsonb,
                            'published',2,42,:started,:confirmed,:started,:confirmed) RETURNING id"""
                ),
                {
                    "package": package_id,
                    "route": route_id,
                    "channel": channel_id,
                    "started": NOW - timedelta(minutes=2),
                    "confirmed": NOW,
                },
            ).scalar_one()
            connection.execute(
                text(
                    """INSERT INTO delivery_attempts
                    (project_id,delivery_id,attempt_no,outcome,started_at,finished_at,message_id)
                    VALUES (1,:delivery,2,'published',:started,:finished,42)"""
                ),
                {
                    "delivery": delivery_id,
                    "started": NOW - timedelta(minutes=2),
                    "finished": NOW,
                },
            )
            connection.execute(
                text(
                    """INSERT INTO operation_runs
                    (project_id,operation,status,outcome,started_at,finished_at)
                    VALUES (1,'publish_once','succeeded','published',:started,:finished)"""
                ),
                {"started": NOW - timedelta(minutes=3), "finished": NOW},
            )

        repository = _repository(engine, 1)
        package = repository.package(1, package_id)
        publication = repository.publications(1)[0]
        operation = repository.operations(1)[0]
        overview = repository.overview(1, DAY, DAY_START, DAY_END)

        assert package.post_text == "Полный текст поста"
        assert package.analysis == "Анализ"
        assert package.source_url == "https://source.test/published"
        assert package.media_available is True
        assert package.media_status == "available"
        assert package.history[0].reason == "approved_by_editor"
        assert package.generation_snapshot["format"] == "practical"
        assert publication.provider == "telegram"
        assert publication.status == "published"
        assert publication.attempts == 2
        assert publication.message_id == 42
        assert publication.failure_code is None
        assert publication.confirmed_at == NOW
        assert operation.kind == "publish_once"
        assert operation.status == "succeeded"
        assert operation.outcome == "published"
        assert operation.duration == timedelta(minutes=3)
        assert overview.published_today == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("limit,offset", [(0, 0), (101, 0), (1, -1)])
def test_list_pagination_is_bounded(
    migrated_database_url: str, limit: int, offset: int
) -> None:
    # Поломка: запрос без границ может читать неограниченный объём данных.
    engine = create_engine(migrated_database_url)
    try:
        with pytest.raises(ValueError):
            _repository(engine, 1).materials(1, limit=limit, offset=offset)
    finally:
        engine.dispose()
