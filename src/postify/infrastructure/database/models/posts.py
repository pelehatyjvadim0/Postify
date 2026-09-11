from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from postify.infrastructure.database.models.base import Base


POST_STATUSES = (
    "generating",
    "needs_review",
    "approved",
    "rejected",
    "failed",
    "published",
)


class PostModel(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_posts_project_id_id"),
        CheckConstraint(
            "status IN ('generating','needs_review','approved','rejected','failed','published')",
            name="ck_posts_status",
        ),
        Index(
            "ix_posts_due",
            "scheduled_at",
            "id",
            postgresql_where=text("status = 'approved'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    post_text: Mapped[str] = mapped_column(Text, nullable=False)
    media_path: Mapped[str | None] = mapped_column(Text)
    media_mime: Mapped[str | None] = mapped_column(String)
    media_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Провайдер, модель, reasoning effort и число итераций правок агента.
    generation: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PostStatusHistoryModel(Base):
    __tablename__ = "post_status_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
