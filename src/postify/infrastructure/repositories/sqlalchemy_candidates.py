from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from postify.domain.candidates.models import Candidate
from postify.infrastructure.database.models import CandidateModel


class SqlAlchemyCandidateRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save_new(self, candidates: Sequence[Candidate]) -> int:
        if not candidates:
            return 0

        rows = [
            {
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
            .on_conflict_do_nothing(constraint="uq_candidates_source_name_source_id")
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
