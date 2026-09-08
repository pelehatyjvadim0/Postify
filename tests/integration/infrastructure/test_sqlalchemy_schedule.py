from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from postify.infrastructure.repositories.sqlalchemy_schedule import SqlAlchemyScheduleRepository


pytestmark = pytest.mark.integration


def _seed_schedule_graph(database_url: str) -> None:
    engine = create_engine(database_url)
    now = datetime(2026, 8, 12, tzinfo=UTC)
    try:
        with engine.begin() as connection:
            for statement in (
                "UPDATE content_projects SET timezone='UTC' WHERE id=1",
                """INSERT INTO source_connections
                    (id,project_id,provider,name,enabled,configuration,schedule,created_at,updated_at)
                    VALUES (101,1,'telegram_account','Source',true,'{}','0 9 * * *',:now,:now)""",
                """INSERT INTO content_formats
                    (id,project_id,name,kind,instructions,enabled,created_at,updated_at)
                    VALUES (201,1,'Format','post','Text',true,:now,:now)""",
                """INSERT INTO channel_connections
                    (id,project_id,provider,name,enabled,configuration,connection_status,created_at,updated_at)
                    VALUES (301,1,'telegram','Channel',true,'{}','ok',:now,:now)""",
                """INSERT INTO publication_routes
                    (id,project_id,format_id,channel_id,enabled,created_at,updated_at)
                    VALUES (401,1,201,301,true,:now,:now)""",
            ):
                connection.execute(text(statement), {"now": now})
    finally:
        engine.dispose()


def test_schedule_reads_source_cron_without_route_autopublish_slots(migrated_database_url: str) -> None:
    _seed_schedule_graph(migrated_database_url)
    engine = create_engine(migrated_database_url)
    try:
        schedules = SqlAlchemyScheduleRepository(sessionmaker(engine)).list_schedules()
    finally:
        engine.dispose()

    assert schedules[0].sources[0].cron == "0 9 * * *"
