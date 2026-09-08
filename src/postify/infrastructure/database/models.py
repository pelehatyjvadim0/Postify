from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CandidateModel(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "source_name",
            "source_id",
            name="uq_candidates_project_source_name_source_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_text: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_connection_id: Mapped[int | None] = mapped_column(BigInteger)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


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
        UniqueConstraint("project_id", "id", name="uq_source_connections_project_id_id"),
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
    __table_args__ = (
        UniqueConstraint(
            "project_id", "id", name="uq_content_formats_project_id_id"
        ),
    )

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


class ChannelConnectionModel(Base):
    __tablename__ = "channel_connections"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "id", name="uq_channel_connections_project_id_id"
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
    encrypted_secret: Mapped[str | None] = mapped_column(Text)
    connection_status: Mapped[str] = mapped_column(String, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PublicationRouteModel(Base):
    __tablename__ = "publication_routes"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "format_id",
            "channel_id",
            name="uq_publication_routes_project_format_channel",
        ),
        UniqueConstraint(
            "project_id", "id", name="uq_publication_routes_project_id_id"
        ),
        ForeignKeyConstraint(
            ["project_id", "format_id"],
            ["content_formats.project_id", "content_formats.id"],
            name="fk_publication_routes_project_format",
        ),
        ForeignKeyConstraint(
            ["project_id", "channel_id"],
            ["channel_connections.project_id", "channel_connections.id"],
            name="fk_publication_routes_project_channel",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    format_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    channel_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScheduleSlotClaimModel(Base):
    __tablename__ = "schedule_slot_claims"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('run_once','publish_once')",
            name="ck_schedule_slot_claims_kind",
        ),
    )

    project_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("content_projects.id"),
        primary_key=True,
    )
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    route_id: Mapped[int | None] = mapped_column(BigInteger)


class ScheduledJobModel(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    route_id: Mapped[int | None] = mapped_column(BigInteger)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    package_id: Mapped[int | None] = mapped_column(BigInteger)
    operation_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TelegramSourceStateModel(Base):
    __tablename__ = "telegram_source_state"
    __table_args__ = (
        CheckConstraint("initial_after_message_id >= 0", name="ck_telegram_source_state_initial_id"),
        ForeignKeyConstraint(
            ["project_id", "source_connection_id"],
            ["source_connections.project_id", "source_connections.id"],
            name="fk_telegram_source_state_project_source",
            ondelete="CASCADE",
        ),
    )

    project_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_connection_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_id: Mapped[str] = mapped_column(String, primary_key=True)
    initial_after_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
