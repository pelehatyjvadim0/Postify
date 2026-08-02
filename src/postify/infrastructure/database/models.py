from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CandidateModel(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint(
            "source_name",
            "source_id",
            name="uq_candidates_source_name_source_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CandidateDecisionModel(Base):
    __tablename__ = "candidate_decisions"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_candidate_decisions_candidate_id"),
        CheckConstraint("status IN ('selected', 'rejected')", name="ck_candidate_decisions_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("candidates.id", name="fk_candidate_decisions_candidate_id_candidates"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    policy_version: Mapped[str] = mapped_column(String, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
