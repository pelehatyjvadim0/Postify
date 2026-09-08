from __future__ import annotations

from dataclasses import dataclass, replace

from postify.application.ports.candidate_repository import CandidateRepository
from postify.application.ports.candidate_source import CandidateSource


@dataclass(frozen=True, slots=True)
class ImportResult:
    received: int
    created: int
    duplicates: int


class ImportCandidates:
    def __init__(self, source: CandidateSource, repository: CandidateRepository, *, source_connection_id: int | None = None) -> None:
        self._source = source
        self._repository = repository
        self._source_connection_id = source_connection_id

    def execute(self) -> ImportResult:
        candidates = self._source.fetch()
        if self._source_connection_id is not None:
            candidates = tuple(replace(item, source_connection_id=self._source_connection_id) for item in candidates)
        received = len(candidates)
        created = self._repository.save_new(candidates)

        if not 0 <= created <= received:
            raise ValueError("created must be between zero and received candidates")

        return ImportResult(
            received=received,
            created=created,
            duplicates=received - created,
        )
