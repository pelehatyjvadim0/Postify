from __future__ import annotations

from dataclasses import dataclass

from postify.application.ports.candidate_repository import CandidateRepository
from postify.application.ports.candidate_source import CandidateSource


@dataclass(frozen=True, slots=True)
class ImportResult:
    received: int
    created: int
    duplicates: int


class ImportCandidates:
    def __init__(self, source: CandidateSource, repository: CandidateRepository) -> None:
        self._source = source
        self._repository = repository

    def execute(self) -> ImportResult:
        candidates = self._source.fetch()
        received = len(candidates)
        created = self._repository.save_new(candidates)

        if not 0 <= created <= received:
            raise ValueError("created must be between zero and received candidates")

        return ImportResult(
            received=received,
            created=created,
            duplicates=received - created,
        )
