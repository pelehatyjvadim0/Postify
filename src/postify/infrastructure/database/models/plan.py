from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from postify.infrastructure.database.models.base import Base


SLOT_STATUSES = (
    "no_topic",
    "planned",
    "generating",
    "needs_review",
    "approved",
    "published",
    "failed",
    "skipped",
)

_STATUS_LIST = ",".join(f"'{status}'" for status in SLOT_STATUSES)


class ContentPlanSlotModel(Base):
    """Слот контент-плана: когда публиковать, в какой рубрике и о чём.

    Ссылки на рубрику и пост составные, через ``project_id``: рубрика или пост
    чужого проекта в слот физически не попадут.
    """

    __tablename__ = "content_plan_slots"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_STATUS_LIST})", name="ck_content_plan_slots_status"
        ),
        UniqueConstraint("project_id", "id", name="uq_content_plan_slots_project_id_id"),
        # Две публикации на одну минуту в один канал не планируются.
        UniqueConstraint(
            "project_id", "publish_at", name="uq_content_plan_slots_project_publish_at"
        ),
        # Пост рождается ровно из одного слота.
        UniqueConstraint(
            "project_id", "post_id", name="uq_content_plan_slots_project_post_id"
        ),
        ForeignKeyConstraint(
            ["project_id", "rubric_id"],
            ["project_rubrics.project_id", "project_rubrics.id"],
            name="fk_content_plan_slots_project_rubric",
        ),
        ForeignKeyConstraint(
            ["project_id", "post_id"],
            ["posts.project_id", "posts.id"],
            name="fk_content_plan_slots_project_post",
        ),
        Index(
            "ix_content_plan_slots_due",
            "project_id",
            "generate_at",
            postgresql_where=text("status = 'planned'"),
        ),
        Index("ix_content_plan_slots_rubric", "project_id", "rubric_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    publish_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Материализовано, а не вычисляется: по нему идёт выборка «пора
    # генерировать», и правка запаса времени не двигает стоящие слоты.
    generate_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    rubric_id: Mapped[int | None] = mapped_column(BigInteger)
    topic: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    post_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
