from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence

import pytest

from postify.application.ingestion.import_candidates import ImportCandidates
from postify.domain.candidates.models import Candidate


def candidate(source_id: str) -> Candidate:
    return Candidate(
        source_name="hacker_news",
        source_id=source_id,
        title=f"Post {source_id}",
        url=f"https://example.test/posts/{source_id}",
        discovered_at=datetime(2026, 8, 1, tzinfo=UTC),
        raw_payload={"objectID": source_id},
    )


class SourceStub:
    def __init__(self, candidates: Sequence[Candidate]) -> None:
        self.candidates = candidates
        self.calls = 0

    def fetch(self) -> Sequence[Candidate]:
        self.calls += 1
        return self.candidates


class RepositorySpy:
    def __init__(self, created: int) -> None:
        self.created = created
        self.calls = 0
        self.received: Sequence[Candidate] | None = None

    def save_new(self, candidates: Sequence[Candidate]) -> int:
        self.calls += 1
        self.received = candidates
        return self.created


def test_imports_candidates_once_in_source_order_and_reports_duplicates() -> None:
    received = [candidate("10"), candidate("20"), candidate("30")]
    source = SourceStub(received)
    repository = RepositorySpy(created=2)

    result = ImportCandidates(source, repository).execute()

    assert result.received == 3
    assert result.created == 2
    assert result.duplicates == 1
    assert source.calls == 1
    assert repository.calls == 1
    assert repository.received is received


@pytest.mark.parametrize("created", [-1, 3])
def test_rejects_repository_count_outside_received_range(created: int) -> None:
    source = SourceStub([candidate("10"), candidate("20")])
    repository = RepositorySpy(created=created)

    with pytest.raises(ValueError, match="created"):
        ImportCandidates(source, repository).execute()


def test_neutral_material_import_uses_server_connection_and_preserves_original():
    material = Candidate(source_name="test_fixture", source_id="document:alpha",
        title="Тестовый материал", url="", discovered_at=datetime(2026, 9, 5, tzinfo=UTC),
        raw_payload={}, source_text="هذا نص للاختبار.", source_connection_id=999)
    repository = RepositorySpy(created=1)

    result = ImportCandidates(SourceStub([material]), repository, source_connection_id=17).execute()

    assert result.created == 1
    stored = repository.received[0]
    assert stored.source_connection_id == 17
    assert stored.source_name == "test_fixture"
    assert stored.source_id == "document:alpha"
    assert stored.source_text == "هذا نص للاختبار."
    assert stored.url == ""
    assert material.source_connection_id == 999
