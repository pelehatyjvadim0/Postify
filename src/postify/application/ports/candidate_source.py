from __future__ import annotations

from typing import Protocol, Sequence

from postify.domain.candidates.models import Candidate


class CandidateSource(Protocol):
    def fetch(self) -> Sequence[Candidate]: ...
