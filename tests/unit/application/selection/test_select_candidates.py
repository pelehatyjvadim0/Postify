from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from postify.domain.candidates.models import Candidate


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def _application_api():
    from postify.application.ports.decision_repository import StoredCandidate
    from postify.application.selection import select_candidates as selection_module
    from postify.application.selection.select_candidates import SelectCandidates, SelectionResult
    from postify.domain.candidates.selection import SelectionProfile
    from postify.domain.candidates.statuses import (
        CandidateDecision,
        DecisionReason,
        DecisionStatus,
    )

    return (
        StoredCandidate,
        selection_module,
        SelectCandidates,
        SelectionResult,
        SelectionProfile,
        CandidateDecision,
        DecisionReason,
        DecisionStatus,
    )


def _candidate(source_id: str) -> Candidate:
    return Candidate(
        source_name="generic_feed",
        source_id=source_id,
        title=f"Материал {source_id}",
        url=f"https://example.test/{source_id}",
        discovered_at=NOW - timedelta(days=1),
        raw_payload={},
    )


def _profile(SelectionProfile):
    return SelectionProfile(
        version="generic-v7",
        language="ru",
        audience="Тестовая аудитория",
        rules=(),
        topic_terms=(),
        topic_exclusion_terms=(),
        advertising_terms=(),
        hiring_terms=(),
        technical_release_terms=(),
        practical_terms=(),
        freshness_window=timedelta(days=30),
    )


@dataclass
class FakeDecisionRepository:
    candidates: list[Any]
    created_ids: set[int]
    find_calls: int = 0
    save_calls: int = 0
    saved_decisions: list[Any] = field(default_factory=list)

    def find_undecided(self):
        self.find_calls += 1
        return list(self.candidates)

    def save_new(self, decisions):
        self.save_calls += 1
        self.saved_decisions = list(decisions)
        return set(self.created_ids)


def test_empty_undecided_set_returns_zero_without_starting_transaction() -> None:
    # Поломка: пустой запуск начинает бессмысленную транзакцию записи.
    (
        _,
        _,
        SelectCandidates,
        SelectionResult,
        SelectionProfile,
        _,
        _,
        _,
    ) = _application_api()
    repository = FakeDecisionRepository([], set())

    result = SelectCandidates(repository, _profile(SelectionProfile), lambda: NOW).execute()

    assert result == SelectionResult(examined=0, selected=0, rejected=0, conflicts=0)
    assert repository.find_calls == 1
    assert repository.save_calls == 0
    assert repository.saved_decisions == []


def test_mixed_decisions_count_only_rows_created_by_this_call(monkeypatch) -> None:
    # Поломка: конкурентно сохранённое решение попадает в selected/rejected текущего запуска.
    (
        StoredCandidate,
        selection_module,
        SelectCandidates,
        SelectionResult,
        SelectionProfile,
        CandidateDecision,
        DecisionReason,
        DecisionStatus,
    ) = _application_api()
    stored = [StoredCandidate(id=value, candidate=_candidate(str(value))) for value in (11, 12, 13)]
    repository = FakeDecisionRepository(stored, {11, 12})
    profile = _profile(SelectionProfile)
    evaluated_profiles: list[object] = []
    clock_calls = 0

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return NOW

    def evaluator(candidate_id, candidate, used_profile, *, now):
        evaluated_profiles.append(used_profile)
        rejected = candidate_id == 12
        return CandidateDecision(
            candidate_id=candidate_id,
            status=DecisionStatus.REJECTED if rejected else DecisionStatus.SELECTED,
            reason=DecisionReason.HIRING if rejected else DecisionReason.ELIGIBLE_FOR_AI,
            explanation="Решение тестовой политики",
            signals={"candidate": candidate.source_id},
            policy_version=used_profile.version,
            decided_at=now,
        )

    monkeypatch.setattr(selection_module, "evaluate_candidate", evaluator)

    result = SelectCandidates(repository, profile, clock).execute()

    assert result == SelectionResult(examined=3, selected=1, rejected=1, conflicts=1)
    assert [decision.candidate_id for decision in repository.saved_decisions] == [11, 12, 13]
    assert [decision.policy_version for decision in repository.saved_decisions] == [
        "generic-v7",
        "generic-v7",
        "generic-v7",
    ]
    assert evaluated_profiles == [profile, profile, profile]
    assert clock_calls == 1
    assert repository.find_calls == 1
    assert repository.save_calls == 1


def test_repository_returning_unknown_candidate_id_is_rejected(monkeypatch) -> None:
    # Поломка: некорректный RETURNING ID нарушает examined == outcomes + conflicts.
    (
        StoredCandidate,
        selection_module,
        SelectCandidates,
        _,
        SelectionProfile,
        CandidateDecision,
        DecisionReason,
        DecisionStatus,
    ) = _application_api()
    repository = FakeDecisionRepository(
        [StoredCandidate(id=21, candidate=_candidate("21"))],
        {999},
    )

    monkeypatch.setattr(
        selection_module,
        "evaluate_candidate",
        lambda candidate_id, candidate, profile, *, now: CandidateDecision(
            candidate_id=candidate_id,
            status=DecisionStatus.SELECTED,
            reason=DecisionReason.ELIGIBLE_FOR_AI,
            explanation="Допущен",
            signals={},
            policy_version=profile.version,
            decided_at=now,
        ),
    )

    with pytest.raises(ValueError, match="999"):
        SelectCandidates(repository, _profile(SelectionProfile), lambda: NOW).execute()


def test_evaluator_error_propagates_without_saving_partial_batch(monkeypatch) -> None:
    # Поломка: evaluator exception скрывается либо уже оценённая часть сохраняется отдельно.
    (
        StoredCandidate,
        selection_module,
        SelectCandidates,
        _,
        SelectionProfile,
        _,
        _,
        _,
    ) = _application_api()
    repository = FakeDecisionRepository(
        [
            StoredCandidate(id=31, candidate=_candidate("31")),
            StoredCandidate(id=32, candidate=_candidate("32")),
        ],
        {31, 32},
    )

    def failing_evaluator(candidate_id, candidate, profile, *, now):
        if candidate_id == 32:
            raise RuntimeError(f"ошибка оценки {candidate_id}")
        from postify.domain.candidates.statuses import (
            CandidateDecision,
            DecisionReason,
            DecisionStatus,
        )

        return CandidateDecision(
            candidate_id=candidate_id,
            status=DecisionStatus.SELECTED,
            reason=DecisionReason.ELIGIBLE_FOR_AI,
            explanation="Допущен",
            signals={},
            policy_version=profile.version,
            decided_at=now,
        )

    monkeypatch.setattr(selection_module, "evaluate_candidate", failing_evaluator)

    with pytest.raises(RuntimeError, match="ошибка оценки 32"):
        SelectCandidates(repository, _profile(SelectionProfile), lambda: NOW).execute()

    assert repository.save_calls == 0
    assert repository.saved_decisions == []
