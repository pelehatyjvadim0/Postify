from __future__ import annotations

from typing import Protocol, Sequence

from postify.domain.candidates.models import Candidate


class SourceFetchError(RuntimeError):
    """Сообщает, что источник кандидатов недоступен или ответил некорректно."""


class CandidateSource(Protocol):
    def fetch(self) -> Sequence[Candidate]: ...
