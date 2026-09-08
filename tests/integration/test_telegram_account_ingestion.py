"""Account paging through the real import/storage boundary; Telegram alone is fake."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from postify.adapters.sources.telegram_account import TelegramAccountReader
from postify.adapters.sources.telegram_group import TelegramGroupSource
from postify.application.ingestion.import_candidates import ImportCandidates
from postify.infrastructure.repositories.sqlalchemy_candidates import SqlAlchemyCandidateRepository
from postify.infrastructure.repositories.sqlalchemy_telegram_source import SqlAlchemyTelegramSourceState
from tests.integration.infrastructure.test_sqlalchemy_schedule import _seed_schedule_graph


pytestmark = pytest.mark.integration
GROUP = "-1001234567890"
NOW = datetime(2026, 9, 5, tzinfo=UTC)


def message(message_id, text_value=None, *, service=False):
    return SimpleNamespace(
        id=message_id,
        raw_text=f"خبر {message_id}" if text_value is None else text_value,
        date=NOW,
        action=object() if service else None,
    )


class TelegramHistory:
    """Implements Telegram's order/filter/limit boundary, without replacing reader logic."""

    def __init__(self):
        self.messages = []
        self.calls = []
        self.disconnects = 0

    def client(self, session_path, api_id, api_hash):
        history = self

        class Client:
            async def connect(self):
                pass

            async def is_user_authorized(self):
                return True

            async def get_input_entity(self, group_id):
                assert group_id == int(GROUP)
                return group_id

            async def iter_messages(self, entity, *, limit, min_id=0, reverse=False):
                history.calls.append({"limit": limit, "min_id": min_id, "reverse": reverse})
                items = sorted(
                    (item for item in history.messages if item.id > min_id),
                    key=lambda item: item.id,
                    reverse=not reverse,
                )
                for item in items if limit is None else items[:limit]:
                    yield item

            async def disconnect(self):
                history.disconnects += 1

        return Client()


@pytest.fixture
def account_import(migrated_database_url, tmp_path):
    _seed_schedule_graph(migrated_database_url)
    engine = create_engine(migrated_database_url)
    sessions = sessionmaker(engine)
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE source_connections SET provider='telegram_group',
                configuration=jsonb_build_object('group_id', CAST(:group_id AS text))
            WHERE project_id=1 AND id=101
        """), {"group_id": GROUP})
    history = TelegramHistory()
    state = SqlAlchemyTelegramSourceState(sessions, project_id=1, source_connection_id=101)
    reader = TelegramAccountReader(
        api_id=123, api_hash="test-only", last_message_id=state.last_message_id,
        initialize=state.initialize,
        session_directory=tmp_path / "telegram", client_factory=history.client,
    )
    source = TelegramGroupSource(connection_id=101, group_id=GROUP, reader=reader, clock=lambda: NOW)
    repository = SqlAlchemyCandidateRepository(sessions, project_id=1)
    try:
        yield SimpleNamespace(
            engine=engine, source=source, state=state, history=history,
            importer=ImportCandidates(source, repository),
        )
    finally:
        engine.dispose()


def stored_message_ids(engine):
    with engine.connect() as connection:
        return connection.execute(text("""
            SELECT (raw_payload->>'message_id')::bigint FROM candidates
            WHERE project_id=1 AND source_connection_id=101
            ORDER BY (raw_payload->>'message_id')::bigint
        """)).scalars().all()


def test_initial_latest100_then_all_downtime_pages_and_repeat_without_duplicates(account_import):
    flow = account_import
    flow.history.messages = [message(number) for number in range(1, 151)]
    assert flow.importer.execute().created == 100
    assert stored_message_ids(flow.engine) == list(range(51, 151))
    assert flow.state.last_message_id(GROUP) == 150

    flow.history.messages.extend(message(number) for number in range(151, 376))
    assert flow.importer.execute().created == 100
    assert stored_message_ids(flow.engine) == list(range(51, 251))
    assert flow.importer.execute().created == 100
    assert stored_message_ids(flow.engine) == list(range(51, 351))
    assert flow.importer.execute().created == 25
    assert flow.importer.execute().created == 0
    assert stored_message_ids(flow.engine) == list(range(51, 376))
    assert flow.state.last_message_id(GROUP) == 375
    assert flow.history.disconnects == 5


def test_empty_and_service_messages_do_not_block_later_text(account_import):
    flow = account_import
    flow.history.messages = [message(100)]
    assert flow.importer.execute().created == 1
    flow.history.messages.extend(message(number, "") for number in range(101, 351))
    flow.history.messages.extend([message(351), message(352, "service action", service=True), message(353)])
    assert flow.importer.execute().created == 2
    assert stored_message_ids(flow.engine) == [100, 351, 353]
    assert flow.state.last_message_id(GROUP) == 353
    assert flow.importer.execute().created == 0


def test_failed_candidate_commit_keeps_watermark_and_replays_messages(account_import):
    flow = account_import
    flow.history.messages = [message(number) for number in range(1, 101)]
    assert flow.importer.execute().created == 100
    flow.history.messages.extend(message(number) for number in range(101, 151))

    class BrokenCommitSession(Session):
        pass

    def fail_commit(session):
        raise RuntimeError("injected_commit_failure")

    event.listen(BrokenCommitSession, "before_commit", fail_commit)
    failing_repository = SqlAlchemyCandidateRepository(sessionmaker(flow.engine, class_=BrokenCommitSession), project_id=1)
    try:
        with pytest.raises(RuntimeError, match="injected_commit_failure"):
            ImportCandidates(flow.source, failing_repository).execute()
    finally:
        event.remove(BrokenCommitSession, "before_commit", fail_commit)
    assert stored_message_ids(flow.engine) == list(range(1, 101))
    assert flow.state.last_message_id(GROUP) == 100
    assert flow.importer.execute().created == 50
    assert stored_message_ids(flow.engine) == list(range(1, 151))


@pytest.mark.parametrize("initial_count", [0, 100])
def test_initial_empty_page_does_not_lose_new_messages_after_downtime(account_import, initial_count):
    # Regression: a missing initial watermark reapplies latest100 after downtime.
    flow = account_import
    flow.history.messages = [message(number, "") for number in range(1, initial_count + 1)]
    assert flow.importer.execute().created == 0
    flow.history.messages.extend(message(number) for number in range(initial_count + 1, initial_count + 151))
    assert flow.importer.execute().created == 100
    assert stored_message_ids(flow.engine) == list(range(initial_count + 1, initial_count + 101))
    assert flow.importer.execute().created == 50
    assert stored_message_ids(flow.engine) == list(range(initial_count + 1, initial_count + 151))
