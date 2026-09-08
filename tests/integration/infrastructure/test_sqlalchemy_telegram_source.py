from dataclasses import replace
from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from postify.domain.candidates.models import Candidate
from postify.infrastructure.repositories.sqlalchemy_candidates import SqlAlchemyCandidateRepository
from postify.infrastructure.repositories.sqlalchemy_telegram_source import SqlAlchemyTelegramSourceState
from tests.integration.infrastructure.test_sqlalchemy_schedule import _seed_schedule_graph


pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 5, tzinfo=UTC)


@pytest.fixture
def source_database(migrated_database_url):
    _seed_schedule_graph(migrated_database_url)
    engine = create_engine(migrated_database_url)
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO source_connections
                (id,project_id,provider,name,enabled,configuration,schedule,created_at,updated_at)
            VALUES (102,1,'telegram_group','Second source',true,'{}','0 9 * * *',:now,:now)
        """), {"now": NOW})
        connection.execute(text("""
            INSERT INTO content_projects
                (id,name,topic,language,audience,timezone,configuration,created_at,updated_at)
            VALUES (2,'Second project','Topic','ru','Audience','UTC','{}',:now,:now)
        """), {"now": NOW})
        connection.execute(text("""
            INSERT INTO source_connections
                (id,project_id,provider,name,enabled,configuration,schedule,created_at,updated_at)
            VALUES (201,2,'telegram_group','Second project source',true,'{}','0 9 * * *',:now,:now)
        """), {"now": NOW})
    try:
        yield engine
    finally:
        engine.dispose()


def candidate(message_id, *, group="-1001", connection=101, source="telegram_group", marker=None):
    return Candidate(
        source_name=source,
        source_id=f"{group}:{message_id if marker is None else marker}",
        title="Тестовый исходный текст",
        url="",
        discovered_at=NOW,
        raw_payload={"group_id": group, "message_id": message_id},
        source_text="نص للاختبار",
        source_connection_id=connection,
    )


def test_watermark_is_none_until_a_candidate_for_that_group_is_saved(source_database):
    sessions = sessionmaker(source_database)
    state = SqlAlchemyTelegramSourceState(sessions, 1, 101)
    assert state.last_message_id("-1001") is None
    assert SqlAlchemyCandidateRepository(sessions).save_new([candidate(17, group="-1002")]) == 1
    assert state.last_message_id("-1001") is None
    assert state.last_message_id("-1002") == 17


def test_watermark_uses_numeric_max_and_isolates_project_connection_group_and_provider(source_database):
    sessions = sessionmaker(source_database)
    repository = SqlAlchemyCandidateRepository(sessions)
    assert repository.save_new([
        candidate(2), candidate(101), candidate(9),
        candidate(999, group="-1002"),
        candidate(1000, connection=102),
        candidate(10000, source="other_source"),
    ]) == 6
    assert SqlAlchemyCandidateRepository(sessions, project_id=2).save_new([candidate(100000, connection=201)]) == 1

    assert SqlAlchemyTelegramSourceState(sessions, 1, 101).last_message_id("-1001") == 101
    assert SqlAlchemyTelegramSourceState(sessions, 1, 102).last_message_id("-1001") == 1000
    assert SqlAlchemyTelegramSourceState(sessions, 2, 201).last_message_id("-1001") == 100000
    assert SqlAlchemyTelegramSourceState(sessions, 2, 101).last_message_id("-1001") is None


def test_malformed_payload_ids_do_not_crash_or_advance_the_watermark(source_database):
    sessions = sessionmaker(source_database)
    malformed = [None, True, "9000", {}, [], 1.5, -1, 0, 10**40, 9223372036854775808]
    records = [candidate(value, marker=f"malformed-{index}") for index, value in enumerate(malformed)]
    records.append(replace(candidate(23, marker="missing-id"), raw_payload={"group_id": "-1001"}))
    repository = SqlAlchemyCandidateRepository(sessions)
    assert repository.save_new(records) == len(records)
    state = SqlAlchemyTelegramSourceState(sessions, 1, 101)
    assert state.last_message_id("-1001") is None
    assert repository.save_new([candidate(23)]) == 1
    assert state.last_message_id("-1001") == 23


def test_failed_atomic_import_does_not_advance_watermark_and_replay_commits_once(source_database):
    sessions = sessionmaker(source_database)
    repository = SqlAlchemyCandidateRepository(sessions)
    assert repository.save_new([candidate(10)]) == 1
    state = SqlAlchemyTelegramSourceState(sessions, 1, 101)
    assert state.initialize("-1001", 5) == 5
    with pytest.raises(IntegrityError):
        repository.save_new([candidate(400), candidate(500, connection=999)])
    assert repository.count() == 1
    assert state.last_message_id("-1001") == 10
    assert SqlAlchemyTelegramSourceState(sessions, 1, 101).initialize("-1001", 999) == 5
    assert repository.save_new([candidate(400)]) == 1
    assert state.last_message_id("-1001") == 400
    assert repository.save_new([candidate(400)]) == 0
    assert SqlAlchemyTelegramSourceState(sessions, 1, 101).last_message_id("-1001") == 400
    assert repository.count() == 2


def test_initial_cutoff_survives_an_empty_import_and_never_moves_on_reinitialization(source_database):
    sessions = sessionmaker(source_database)
    state = SqlAlchemyTelegramSourceState(sessions, 1, 101)
    assert state.initialize("-1001", 100) == 100
    assert SqlAlchemyTelegramSourceState(sessions, 1, 101).last_message_id("-1001") == 100
    assert state.initialize("-1001", 900) == 100
    repository = SqlAlchemyCandidateRepository(sessions)
    assert repository.save_new([candidate(99)]) == 1
    assert state.last_message_id("-1001") == 100
    assert repository.save_new([candidate(101)]) == 1
    assert state.last_message_id("-1001") == 101
    assert state.initialize("-1001", 1000) == 100
    assert state.last_message_id("-1001") == 101
    assert state.initialize("-1002", 0) == 0
    assert SqlAlchemyTelegramSourceState(sessions, 1, 101).last_message_id("-1002") == 0


def test_concurrent_initialization_keeps_one_committed_first_cutoff(source_database):
    sessions = sessionmaker(source_database)
    ready = Barrier(2)
    def initialize(value):
        state = SqlAlchemyTelegramSourceState(sessions, 1, 101)
        ready.wait(timeout=5)
        return state.initialize("-1001", value)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(initialize, [100, 200]))
    assert results[0] == results[1]
    assert results[0] in {100, 200}
    assert SqlAlchemyTelegramSourceState(sessions, 1, 101).last_message_id("-1001") == results[0]
    with source_database.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM telegram_source_state")).scalar_one() == 1


def test_initial_cutoff_is_scoped_and_source_deletion_cascades_without_touching_other_sources(source_database):
    sessions = sessionmaker(source_database)
    state = SqlAlchemyTelegramSourceState(sessions, 1, 101)
    assert state.initialize("-1001", 10) == 10
    assert state.initialize("-1002", 11) == 11
    assert SqlAlchemyTelegramSourceState(sessions, 1, 102).initialize("-1001", 12) == 12
    assert SqlAlchemyTelegramSourceState(sessions, 2, 201).initialize("-1001", 13) == 13
    with pytest.raises(IntegrityError):
        SqlAlchemyTelegramSourceState(sessions, 2, 101).initialize("-1001", 999)
    assert state.last_message_id("-1001") == 10
    assert state.last_message_id("-1002") == 11
    with source_database.begin() as connection:
        connection.execute(text("DELETE FROM source_connections WHERE project_id=1 AND id=101"))
    assert state.last_message_id("-1001") is None
    assert state.last_message_id("-1002") is None
    assert SqlAlchemyTelegramSourceState(sessions, 1, 102).last_message_id("-1001") == 12
    assert SqlAlchemyTelegramSourceState(sessions, 2, 201).last_message_id("-1001") == 13


def test_negative_initial_cutoff_is_rejected_by_repository_and_database(source_database):
    sessions = sessionmaker(source_database)
    state = SqlAlchemyTelegramSourceState(sessions, 1, 101)
    with pytest.raises(ValueError):
        state.initialize("-1001", -1)
    with pytest.raises(IntegrityError):
        with source_database.begin() as connection:
            connection.execute(text("INSERT INTO telegram_source_state(project_id,source_connection_id,group_id,initial_after_message_id) VALUES (1,101,'-1001',-1)"))
    assert state.last_message_id("-1001") is None
