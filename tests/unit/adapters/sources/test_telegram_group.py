from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from postify.adapters.sources.registry import SourceProviderRegistry
from postify.adapters.sources.telegram_group import TelegramGroupSource, TelegramMessage
from postify.application.ingestion.import_candidates import ImportCandidates
from postify.application.ports.candidate_source import SourceFetchError


NOW = datetime(2026, 9, 5, tzinfo=UTC)


def test_telegram_maps_original_without_needing_public_link_or_language_setting():
    calls = []
    def reader(group):
        calls.append(group)
        return [TelegramMessage(12, "افتتحت المكتبة اليوم.\n300 كتاب", NOW), TelegramMessage(13, " ")]
    result = TelegramGroupSource(connection_id=9, group_id="private-group", reader=reader, clock=lambda: NOW).fetch()
    assert calls == ["private-group"]
    assert len(result) == 1
    material = result[0]
    assert material.source_id == "private-group:12"
    assert material.source_connection_id == 9
    assert material.source_text == "افتتحت المكتبة اليوم.\n300 كتاب"
    assert material.url == ""
    assert material.published_at == NOW
    assert material.discovered_at == NOW


def test_registry_never_assumes_unconfigured_telegram_access():
    connection = SimpleNamespace(id=4, provider="telegram_group", configuration={"group_id": "private"})
    source = SourceProviderRegistry().create(connection, client=None)
    with pytest.raises(SourceFetchError, match="source_access_not_configured"):
        source.fetch()


@pytest.mark.parametrize("messages", [[TelegramMessage(0, "text")], [TelegramMessage(1, "text", datetime(2026, 1, 1))]])
def test_malformed_batch_is_reported_instead_of_silently_dropping_material(messages):
    source = TelegramGroupSource(connection_id=2, group_id="group", reader=lambda group: messages)
    with pytest.raises(SourceFetchError, match="^telegram_source_failed$"):
        source.fetch()


def test_reader_error_is_safe_and_import_does_not_write_partial_batch():
    def reader(group):
        raise RuntimeError("private-session-details")
    source = TelegramGroupSource(connection_id=2, group_id="group", reader=reader)
    writes = []
    with pytest.raises(SourceFetchError) as caught:
        ImportCandidates(source, SimpleNamespace(save_new=lambda values: writes.append(values))).execute()
    assert str(caught.value) == "telegram_source_failed"
    assert writes == []


def test_changing_group_keeps_same_message_number_distinct_for_import_deduplication():
    def fetch(group):
        return TelegramGroupSource(connection_id=9, group_id=group,
            reader=lambda requested: [TelegramMessage(17, "Текст сообщения")],
            clock=lambda: NOW).fetch()[0]

    first = fetch("group-a")
    replay = fetch("group-a")
    changed = fetch("group-b")

    assert first.source_connection_id == changed.source_connection_id == 9
    assert first.source_id == replay.source_id
    assert first.source_id != changed.source_id
