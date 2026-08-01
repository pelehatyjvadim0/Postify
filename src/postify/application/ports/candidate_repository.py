from __future__ import annotations

from typing import Protocol, Sequence

from postify.domain.candidates.models import Candidate


class CandidateRepository(Protocol):
    def save_new(self, candidates: Sequence[Candidate]) -> int: ...

    def count(self) -> int: ...
