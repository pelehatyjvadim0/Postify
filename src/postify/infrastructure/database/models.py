from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
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


class ContentProjectModel(Base):
    __tablename__ = "content_projects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String, nullable=False)
    audience: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(String, nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceConnectionModel(Base):
    __tablename__ = "source_connections"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "name", name="uq_source_connections_project_id_name"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schedule: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContentFormatModel(Base):
    __tablename__ = "content_formats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CallToActionModel(Base):
    __tablename__ = "calls_to_action"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    link_mode: Mapped[str] = mapped_column(String, nullable=False)
    custom_url: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChannelConnectionModel(Base):
    __tablename__ = "channel_connections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    encrypted_secret: Mapped[str | None] = mapped_column(Text)
    connection_status: Mapped[str] = mapped_column(String, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PublicationRouteModel(Base):
    __tablename__ = "publication_routes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    format_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_formats.id"), nullable=False
    )
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("channel_connections.id"), nullable=False
    )
    cta_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("calls_to_action.id")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    schedule: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
