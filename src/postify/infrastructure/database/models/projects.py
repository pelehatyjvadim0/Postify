from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from postify.infrastructure.database.models.base import Base


class ContentProjectModel(Base):
    __tablename__ = "content_projects"
    __table_args__ = (
        CheckConstraint(
            "publication_mode IN ('review','auto')",
            name="ck_content_projects_publication_mode",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Проект принадлежит одному пользователю; совместной работы нет.
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Промпт проекта — третий уровень контекста генерации.
    project_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String, nullable=False)
    audience: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(String, nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Запас времени на генерацию: слот считает generate_at как publish_at минус это.
    generation_lead_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1440")
    )
    # review — каждый пост ждёт одобрения, auto — зелёный пост уходит сам.
    publication_mode: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'review'")
    )
    # Сколько дней изображение не предлагается повторно.
    media_reuse_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("30")
    )
    media_reuse_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectRubricModel(Base):
    """Рубрика проекта: форма поста и редакционные инструкции."""

    __tablename__ = "project_rubrics"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_project_rubrics_project_id_id"),
        UniqueConstraint(
            "project_id", "name", name="uq_project_rubrics_project_id_name"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChannelConnectionModel(Base):
    """Канал проекта. Проект равен одному каналу, поэтому project_id уникален."""

    __tablename__ = "channel_connections"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_channel_connections_project_id"),
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
