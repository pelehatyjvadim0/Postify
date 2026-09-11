from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from postify.infrastructure.database.models.base import Base


JOB_KINDS = "'generate_post','publish_once'"


class ScheduleSlotClaimModel(Base):
    """Идемпотентность расписания: слот проекта занимается один раз."""

    __tablename__ = "schedule_slot_claims"
    __table_args__ = (
        CheckConstraint(f"kind IN ({JOB_KINDS})", name="ck_schedule_slot_claims_kind"),
        ForeignKeyConstraint(
            ["project_id", "post_id"],
            ["posts.project_id", "posts.id"],
            name="fk_schedule_slot_claims_project_post",
        ),
        ForeignKeyConstraint(
            ["project_id", "slot_id"],
            ["content_plan_slots.project_id", "content_plan_slots.id"],
            name="fk_schedule_slot_claims_project_slot",
        ),
        Index(
            "uq_schedule_slot_claims_slot",
            "project_id",
            "kind",
            "scheduled_for",
            text("COALESCE(post_id, 0)"),
            text("COALESCE(slot_id, 0)"),
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    post_id: Mapped[int | None] = mapped_column(BigInteger)
    # Цель задачи генерации: поста в этот момент ещё нет, есть слот плана.
    slot_id: Mapped[int | None] = mapped_column(BigInteger)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ScheduledJobModel(Base):
    """Задача, переживающая перезапуск процесса."""

    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        CheckConstraint(f"kind IN ({JOB_KINDS})", name="ck_scheduled_jobs_kind"),
        CheckConstraint(
            "status IN ('queued','leased','succeeded','failed')",
            name="ck_scheduled_jobs_status",
        ),
        ForeignKeyConstraint(
            ["project_id", "post_id"],
            ["posts.project_id", "posts.id"],
            name="fk_scheduled_jobs_project_post",
        ),
        ForeignKeyConstraint(
            ["project_id", "slot_id"],
            ["content_plan_slots.project_id", "content_plan_slots.id"],
            name="fk_scheduled_jobs_project_slot",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    post_id: Mapped[int | None] = mapped_column(BigInteger)
    slot_id: Mapped[int | None] = mapped_column(BigInteger)
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    operation_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("operation_runs.id"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
