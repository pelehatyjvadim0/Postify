from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from postify.domain.candidates.models import Candidate
from postify.domain.candidates.statuses import CandidateDecision


@dataclass(frozen=True, slots=True)
class StoredCandidate:
    id: int
    candidate: Candidate


class DecisionRepository(Protocol):
    def find_undecided(self) -> Sequence[StoredCandidate]: ...

    def save_new(self, decisions: Sequence[CandidateDecision]) -> set[int]: ...
