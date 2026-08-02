from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from postify.application.ports.decision_repository import StoredCandidate
from postify.domain.candidates.models import Candidate
from postify.domain.candidates.statuses import CandidateDecision
from postify.infrastructure.database.models import CandidateDecisionModel, CandidateModel


class SqlAlchemyDecisionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def find_undecided(self) -> list[StoredCandidate]:
        statement = (
            select(CandidateModel)
            .outerjoin(CandidateDecisionModel, CandidateDecisionModel.candidate_id == CandidateModel.id)
            .where(CandidateDecisionModel.id.is_(None))
            .order_by(CandidateModel.id)
        )
        with self._session_factory() as session:
            return [
                StoredCandidate(
                    id=model.id,
                    candidate=Candidate(
                        source_name=model.source_name,
                        source_id=model.source_id,
                        title=model.title,
                        url=model.url,
                        discovered_at=model.discovered_at,
                        raw_payload=model.raw_payload,
                    ),
                )
                for model in session.scalars(statement)
            ]

    def save_new(self, decisions: Sequence[CandidateDecision]) -> set[int]:
        if not decisions:
            return set()
        rows = [
            {
                "candidate_id": decision.candidate_id,
                "status": decision.status.value,
                "reason": decision.reason.value,
                "explanation": decision.explanation,
                "signals": dict(decision.signals),
                "policy_version": decision.policy_version,
                "decided_at": decision.decided_at,
            }
            for decision in decisions
        ]
        statement = (
            insert(CandidateDecisionModel)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_candidate_decisions_candidate_id")
            .returning(CandidateDecisionModel.candidate_id)
        )
        with self._session_factory() as session:
            try:
                created = set(session.scalars(statement).all())
                session.commit()
                return created
            except Exception:
                session.rollback()
                raise
