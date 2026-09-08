import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from postify.adapters.sources.telegram_account import TelegramAccountReader
from postify.application.ports.candidate_source import SourceFetchError


GROUP = "-1004450456097"
NOW = datetime(2026, 9, 5, tzinfo=UTC)


def message(identifier, body="نص تجريبي", action=None):
    return SimpleNamespace(id=identifier, raw_text=body, date=NOW, action=action)


class Client:
    def __init__(self, messages=(), *, authorized=True, failure=None):
        self.messages = list(messages)
        self.authorized = authorized
        self.failure = failure
        self.events = []

    async def connect(self):
        self.events.append("connect")
        if self.failure:
            raise self.failure

    async def is_user_authorized(self):
        self.events.append("authorized")
        return self.authorized

    async def get_input_entity(self, group):
        self.events.append(("entity", group))
        return "cached-entity"

    async def iter_messages(self, entity, **options):
        self.events.append(("messages", entity, options))
        messages = [item for item in self.messages if item.id > options.get("min_id", 0)]
        messages.sort(key=lambda item: item.id, reverse=not options.get("reverse", False))
        limit = options["limit"]
        for item in messages if limit is None else messages[:limit]:
            yield item

    async def disconnect(self):
        self.events.append("disconnect")


def reader(tmp_path, client, watermark=None):
    return TelegramAccountReader(api_id=123, api_hash="test-only-hash",
        last_message_id=lambda group: watermark, session_directory=tmp_path / "session",
        initialize=lambda group, boundary: boundary,
        client_factory=lambda session, api_id, api_hash: client)


def test_initial_read_is_latest_hundred_in_ascending_order(tmp_path):
    client = Client([message(i) for i in range(1, 151)])

    result = reader(tmp_path, client)(GROUP)

    assert [item.message_id for item in result] == list(range(51, 151))
    assert result[0].text == "نص تجريبي" and result[0].published_at == NOW
    assert ("entity", -1004450456097) in client.events
    assert ("messages", "cached-entity", {"limit": 100}) in client.events
    assert ("messages", "cached-entity", {"min_id": 50, "reverse": True, "limit": None}) in client.events
    assert client.events[-1] == "disconnect"


def test_backlog_reads_oldest_new_texts_and_does_not_count_empty_or_service_messages(tmp_path):
    messages = [message(i, "" if i % 2 else "نص") for i in range(1, 281)]
    messages.append(message(281, "Service text", action=object()))
    client = Client(messages)

    result = reader(tmp_path, client, watermark=20)(GROUP)

    assert [item.message_id for item in result] == list(range(22, 222, 2))
    assert ("messages", "cached-entity", {"min_id": 20, "reverse": True, "limit": None}) in client.events
    assert client.events[-1] == "disconnect"


def test_service_and_whitespace_texts_are_not_returned(tmp_path):
    client = Client([message(1, "\n \t"), message(2, "service", action=object()), message(3)])
    assert [item.message_id for item in reader(tmp_path, client)(GROUP)] == [3]


def test_reader_has_no_memory_cursor_before_import_commit(tmp_path):
    client = Client([message(11), message(12)])
    read = reader(tmp_path, client, watermark=10)

    first = read(GROUP)
    replay = read(GROUP)

    assert [item.message_id for item in first] == [11, 12]
    assert replay == first
    assert client.events.count("disconnect") == 2


def test_initial_blank_window_persists_boundary_and_does_not_import_older_texts(tmp_path):
    client = Client([message(1, "Old text")] + [message(i, "") for i in range(2, 102)])
    boundaries = {}
    def initialize(group, boundary):
        return boundaries.setdefault(group, boundary)
    read = TelegramAccountReader(api_id=123, api_hash="test-only-hash",
        last_message_id=boundaries.get, initialize=initialize,
        session_directory=tmp_path / "session", client_factory=lambda *args: client)

    assert read(GROUP) == ()
    assert boundaries == {GROUP: 1}
    client.messages.append(message(102, "New text"))
    assert [item.message_id for item in read(GROUP)] == [102]
    assert client.events.count(("messages", "cached-entity", {"limit": 100})) == 1


def test_concurrent_initialization_uses_persisted_winning_boundary(tmp_path):
    client = Client([message(i) for i in range(1, 151)])
    read = TelegramAccountReader(api_id=123, api_hash="test-only-hash",
        last_message_id=lambda group: None, initialize=lambda group, boundary: 20,
        session_directory=tmp_path / "session", client_factory=lambda *args: client)

    result = read(GROUP)

    assert [item.message_id for item in result] == list(range(21, 121))
    assert ("messages", "cached-entity", {"min_id": 20, "reverse": True, "limit": None}) in client.events


def test_unauthorized_account_is_not_prompted_and_lock_is_released(tmp_path):
    client = Client(authorized=False)
    read = reader(tmp_path, client)
    with pytest.raises(SourceFetchError, match="^telegram_account_not_authorized$"):
        read(GROUP)
    assert client.events == ["connect", "authorized", "disconnect"]
    client.authorized = True
    assert read(GROUP) == ()


@pytest.mark.parametrize("failure,code", [
    (asyncio.TimeoutError("private-detail"), "telegram_source_timeout"),
    (RuntimeError("private-detail"), "telegram_account_unavailable"),
])
def test_network_failures_are_safe_and_disconnect_even_when_connect_fails(tmp_path, failure, code):
    client = Client(failure=failure)
    with pytest.raises(SourceFetchError) as caught:
        reader(tmp_path, client)(GROUP)
    assert str(caught.value) == code
    assert client.events == ["connect", "disconnect"]
