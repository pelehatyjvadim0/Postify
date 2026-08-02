from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from postify.application.ports.decision_repository import DecisionRepository
from postify.domain.candidates.selection import SelectionProfile, evaluate_candidate
from postify.domain.candidates.statuses import DecisionStatus


@dataclass(frozen=True, slots=True)
class SelectionResult:
    examined: int
    selected: int
    rejected: int
    conflicts: int


class SelectCandidates:
    def __init__(
        self, repository: DecisionRepository, profile: SelectionProfile, clock: Callable[[], datetime]
    ) -> None:
        self._repository = repository
        self._profile = profile
        self._clock = clock

    def execute(self) -> SelectionResult:
        candidates = self._repository.find_undecided()
        if not candidates:
            return SelectionResult(examined=0, selected=0, rejected=0, conflicts=0)
        now = self._clock()
        decisions = [
            evaluate_candidate(item.id, item.candidate, self._profile, now=now)
            for item in candidates
        ]
        created_ids = self._repository.save_new(decisions)
        known_ids = {decision.candidate_id for decision in decisions}
        unknown_ids = created_ids - known_ids
        if unknown_ids:
            raise ValueError(f"repository returned unknown candidate IDs: {sorted(unknown_ids)}")
        selected = sum(
            decision.status is DecisionStatus.SELECTED and decision.candidate_id in created_ids
            for decision in decisions
        )
        rejected = sum(
            decision.status is DecisionStatus.REJECTED and decision.candidate_id in created_ids
            for decision in decisions
        )
        return SelectionResult(
            examined=len(decisions), selected=selected, rejected=rejected,
            conflicts=len(decisions) - len(created_ids),
        )
