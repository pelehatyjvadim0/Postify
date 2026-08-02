from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from postify.domain.candidates.models import Candidate
from postify.infrastructure.database.models import CandidateModel


pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


class TransactionTrackingSession(Session):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.commit_calls = 0
        self.rollback_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1
        super().commit()

    def rollback(self) -> None:
        self.rollback_calls += 1
        super().rollback()


def _repository_api():
    from postify.domain.candidates.statuses import (
        CandidateDecision,
        DecisionReason,
        DecisionStatus,
    )
    from postify.infrastructure.repositories.sqlalchemy_decisions import (
        SqlAlchemyDecisionRepository,
    )

    return SqlAlchemyDecisionRepository, CandidateDecision, DecisionReason, DecisionStatus


def _candidate(source_id: str, **overrides: object) -> Candidate:
    values: dict[str, object] = {
        "source_name": "generic_feed",
        "source_id": source_id,
        "title": f"Материал {source_id}",
        "url": f"https://example.test/{source_id}",
        "discovered_at": NOW - timedelta(days=1),
        "raw_payload": {"source_field": source_id},
    }
    values.update(overrides)
    return Candidate(**values)  # type: ignore[arg-type]


def _seed_candidates(session_factory, source_ids: tuple[str, ...]) -> list[int]:
    with session_factory() as session:
        models = [
            CandidateModel(
                source_name="generic_feed",
                source_id=source_id,
                title=f"Материал {source_id}",
                url=f"https://example.test/{source_id}",
                discovered_at=NOW - timedelta(days=1),
                raw_payload={"source_field": source_id},
            )
            for source_id in source_ids
        ]
        session.add_all(models)
        session.commit()
        return [model.id for model in models]


def _decision(candidate_id: int, **overrides: object):
    _, CandidateDecision, DecisionReason, DecisionStatus = _repository_api()
    values: dict[str, object] = {
        "candidate_id": candidate_id,
        "status": DecisionStatus.SELECTED,
        "reason": DecisionReason.ELIGIBLE_FOR_AI,
        "explanation": "Допущен к будущему AI-анализу",
        "signals": {"freshness": "fresh", "matched_terms": []},
        "policy_version": "generic-v1",
        "decided_at": NOW,
    }
    values.update(overrides)
    return CandidateDecision(**values)


def test_find_undecided_returns_all_runs_in_candidate_id_order_with_exact_domain_fields(
    migrated_database_url: str,
) -> None:
    # Поломка (mutation 11): выбираются только записи текущего импорта или теряются поля домена.
    SqlAlchemyDecisionRepository, _, _, _ = _repository_api()
    engine = create_engine(migrated_database_url)
    session_factory = sessionmaker(engine)
    candidate_ids = _seed_candidates(session_factory, ("earlier", "decided", "latest"))
    repository = SqlAlchemyDecisionRepository(session_factory)

    try:
        assert repository.save_new([_decision(candidate_ids[1])]) == {candidate_ids[1]}

        undecided = repository.find_undecided()

        assert [item.id for item in undecided] == [candidate_ids[0], candidate_ids[2]]
        assert [item.candidate for item in undecided] == [
            _candidate("earlier"),
            _candidate("latest"),
        ]
    finally:
        engine.dispose()


def test_save_new_persists_every_decision_field_exactly_and_commits_one_batch(
    migrated_database_url: str,
) -> None:
    # Поломка (mutation 7/10): reason/signals/version теряются либо пакет делает несколько commit.
    SqlAlchemyDecisionRepository, _, DecisionReason, DecisionStatus = _repository_api()
    engine = create_engine(migrated_database_url)
    session_factory = sessionmaker(engine)
    candidate_ids = _seed_candidates(session_factory, ("one", "two"))
    tracking_session = TransactionTrackingSession(bind=engine)
    repository = SqlAlchemyDecisionRepository(lambda: tracking_session)  # type: ignore[arg-type]
    decisions = [
        _decision(candidate_ids[0]),
        _decision(
            candidate_ids[1],
            status=DecisionStatus.REJECTED,
            reason=DecisionReason.HIRING,
            explanation="Обнаружено объявление о найме",
            signals={"matched_rule": "hiring", "matched_terms": ["вакансия"]},
            policy_version="generic-v2",
            decided_at=NOW + timedelta(minutes=1),
        ),
    ]

    try:
        assert repository.save_new(decisions) == set(candidate_ids)
        assert tracking_session.commit_calls == 1
        assert tracking_session.rollback_calls == 0

        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT candidate_id, status, reason, explanation, signals, "
                    "policy_version, decided_at FROM candidate_decisions ORDER BY candidate_id"
                )
            ).mappings().all()

        assert [dict(row) for row in rows] == [
            {
                "candidate_id": candidate_ids[0],
                "status": "selected",
                "reason": "eligible_for_ai",
                "explanation": "Допущен к будущему AI-анализу",
                "signals": {"freshness": "fresh", "matched_terms": []},
                "policy_version": "generic-v1",
                "decided_at": NOW,
            },
            {
                "candidate_id": candidate_ids[1],
                "status": "rejected",
                "reason": "hiring",
                "explanation": "Обнаружено объявление о найме",
                "signals": {"matched_rule": "hiring", "matched_terms": ["вакансия"]},
                "policy_version": "generic-v2",
                "decided_at": NOW + timedelta(minutes=1),
            },
        ]
    finally:
        tracking_session.close()
        engine.dispose()


def test_save_new_converts_recursively_frozen_signals_to_jsonb_values(
    migrated_database_url: str,
) -> None:
    # Поломка Important: immutable JSON-представление нельзя сериализовать в JSONB без thaw.
    SqlAlchemyDecisionRepository, _, _, _ = _repository_api()
    engine = create_engine(migrated_database_url)
    session_factory = sessionmaker(engine)
    candidate_id = _seed_candidates(session_factory, ("frozen-signals",))[0]
    repository = SqlAlchemyDecisionRepository(session_factory)
    expected_signals = {
        "freshness": {"state": "fresh", "age_days": 1},
        "matched_terms": ["руководство"],
        "evidence": [{"field": "title", "matched": True}],
    }
    decision = _decision(candidate_id, signals=expected_signals)

    try:
        with pytest.raises((TypeError, AttributeError)):
            decision.signals["freshness"]["state"] = "stale"  # type: ignore[index]

        assert repository.save_new([decision]) == {candidate_id}

        with engine.connect() as connection:
            stored_signals = connection.execute(
                text(
                    "SELECT signals FROM candidate_decisions "
                    "WHERE candidate_id = :candidate_id"
                ),
                {"candidate_id": candidate_id},
            ).scalar_one()

        assert isinstance(stored_signals, dict)
        assert isinstance(stored_signals["freshness"], dict)
        assert isinstance(stored_signals["matched_terms"], list)
        assert isinstance(stored_signals["evidence"], list)
        assert isinstance(stored_signals["evidence"][0], dict)
        assert stored_signals == expected_signals
    finally:
        engine.dispose()


def test_save_new_is_immutable_and_idempotent_without_overwrite(
    migrated_database_url: str,
) -> None:
    # Поломка (mutation 8/9): повтор создаёт вторую строку или обновляет первое решение.
    SqlAlchemyDecisionRepository, _, DecisionReason, DecisionStatus = _repository_api()
    engine = create_engine(migrated_database_url)
    session_factory = sessionmaker(engine)
    candidate_id = _seed_candidates(session_factory, ("immutable",))[0]
    repository = SqlAlchemyDecisionRepository(session_factory)
    original = _decision(candidate_id)
    replacement = _decision(
        candidate_id,
        status=DecisionStatus.REJECTED,
        reason=DecisionReason.ADVERTISING,
        explanation="Подмена",
        signals={"matched_rule": "advertising"},
        policy_version="replacement",
        decided_at=NOW + timedelta(days=1),
    )

    try:
        assert repository.save_new([original]) == {candidate_id}
        assert repository.save_new([replacement]) == set()

        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT status, reason, explanation, signals, policy_version, decided_at "
                    "FROM candidate_decisions WHERE candidate_id = :candidate_id"
                ),
                {"candidate_id": candidate_id},
            ).mappings().all()

        assert [dict(row) for row in rows] == [
            {
                "status": "selected",
                "reason": "eligible_for_ai",
                "explanation": "Допущен к будущему AI-анализу",
                "signals": {"freshness": "fresh", "matched_terms": []},
                "policy_version": "generic-v1",
                "decided_at": NOW,
            }
        ]
    finally:
        engine.dispose()


def test_concurrent_overlapping_inserts_create_one_immutable_decision(
    migrated_database_url: str,
) -> None:
    # Поломка: проверка then-insert гоняется и позволяет двум потокам создать решение.
    SqlAlchemyDecisionRepository, _, DecisionReason, DecisionStatus = _repository_api()
    engine = create_engine(migrated_database_url)
    session_factory = sessionmaker(engine)
    candidate_id = _seed_candidates(session_factory, ("concurrent",))[0]
    repository = SqlAlchemyDecisionRepository(session_factory)
    insert_barrier = Barrier(2)

    def synchronize_decision_inserts(
        connection, cursor, statement, parameters, context, executemany
    ) -> None:
        if statement.startswith("INSERT INTO candidate_decisions"):
            insert_barrier.wait(timeout=5)

    event.listen(engine, "before_cursor_execute", synchronize_decision_inserts)
    decisions = [
        _decision(candidate_id),
        _decision(
            candidate_id,
            status=DecisionStatus.REJECTED,
            reason=DecisionReason.HIRING,
            explanation="Конкурентный вариант",
            policy_version="concurrent-v2",
        ),
    ]

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            created_sets = list(executor.map(lambda item: repository.save_new([item]), decisions))

        with session_factory() as session:
            total = session.execute(text("SELECT count(*) FROM candidate_decisions")).scalar_one()

        assert sum(len(created) for created in created_sets) == 1
        assert total == 1
        assert {frozenset(created) for created in created_sets} == {
            frozenset(),
            frozenset({candidate_id}),
        }
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_decision_inserts)
        engine.dispose()


def test_failed_batch_rolls_back_atomically_and_reuses_same_session(
    migrated_database_url: str,
) -> None:
    # Поломка (mutation 10): нет явного rollback, часть пакета остаётся или session отравлена.
    SqlAlchemyDecisionRepository, _, _, _ = _repository_api()
    engine = create_engine(migrated_database_url)
    session_factory = sessionmaker(engine)
    candidate_ids = _seed_candidates(session_factory, ("valid", "invalid"))
    tracking_session = TransactionTrackingSession(bind=engine)
    repository = SqlAlchemyDecisionRepository(lambda: tracking_session)  # type: ignore[arg-type]
    invalid = _decision(candidate_ids[1], signals={"not_json": object()})

    try:
        with pytest.raises(TypeError, match="not JSON serializable"):
            repository.save_new([_decision(candidate_ids[0]), invalid])

        assert tracking_session.rollback_calls == 1
        with session_factory() as verification_session:
            after_failure = verification_session.execute(
                text("SELECT count(*) FROM candidate_decisions")
            ).scalar_one()
        assert after_failure == 0

        assert repository.save_new([_decision(candidate_ids[0])]) == {candidate_ids[0]}
        assert tracking_session.commit_calls == 1
        with session_factory() as verification_session:
            after_reuse = verification_session.execute(
                text("SELECT count(*) FROM candidate_decisions")
            ).scalar_one()
        assert after_reuse == 1
    finally:
        tracking_session.close()
        engine.dispose()
