from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from postify.domain.candidates.models import Candidate
from postify.infrastructure.database.models import CandidateModel


class SqlAlchemyCandidateRepository:
    def __init__(self, session_factory: sessionmaker[Session], project_id: int = 1) -> None:
        self._session_factory = session_factory
        self._project_id = project_id

    def save_new(self, candidates: Sequence[Candidate]) -> int:
        if not candidates:
            return 0

        rows = [
            {
                "project_id": self._project_id,
                "source_name": candidate.source_name,
                "source_id": candidate.source_id,
                "title": candidate.title,
                "url": candidate.url,
                "discovered_at": candidate.discovered_at,
                "raw_payload": dict(candidate.raw_payload),
            }
            for candidate in candidates
        ]
        statement = (
            insert(CandidateModel)
            .values(rows)
            .on_conflict_do_nothing(
                constraint="uq_candidates_project_source_name_source_id"
            )
            .returning(CandidateModel.id)
        )

        with self._session_factory() as session:
            try:
                created = len(session.scalars(statement).all())
                session.commit()
                return created
            except Exception:
                session.rollback()
                raise

    def count(self) -> int:
        with self._session_factory() as session:
            return session.scalar(
                select(func.count())
                .select_from(CandidateModel)
                .where(CandidateModel.project_id == self._project_id)
            ) or 0
