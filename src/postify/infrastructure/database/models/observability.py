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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from postify.infrastructure.database.models.base import Base

from postify.domain.observability.models import OperationKind


OPERATION_KINDS = tuple(kind.value for kind in OperationKind)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ",".join(f"'{value}'" for value in values) + ")"


class OperationRunModel(Base):
    """Одна длительная операция проекта; UI опрашивает её по id."""

    __tablename__ = "operation_runs"
    __table_args__ = (
        CheckConstraint(_in_list("operation", OPERATION_KINDS), name="ck_operation_runs_operation"),
        CheckConstraint(
            "status IN ('running','succeeded','failed')",
            name="ck_operation_runs_status",
        ),
        CheckConstraint(
            "(mode = 'automatic' AND actor = 'scheduler')"
            " OR (mode = 'manual' AND actor = 'user')",
            name="ck_operation_runs_context",
        ),
        CheckConstraint(
            "(status = 'running' AND outcome IS NULL AND failure_code IS NULL"
            " AND finished_at IS NULL)"
            " OR (status = 'succeeded' AND btrim(outcome) <> '' AND failure_code IS NULL"
            " AND finished_at IS NOT NULL)"
            " OR (status = 'failed' AND outcome IS NULL AND btrim(failure_code) <> ''"
            " AND finished_at IS NOT NULL AND failure_code = operation || '_failed')",
            name="ck_operation_runs_terminal_fields",
        ),
        Index(
            "uq_operation_runs_active_project_operation",
            "project_id",
            "operation",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String)
    failure_code: Mapped[str | None] = mapped_column(String)
    mode: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'automatic'")
    )
    actor: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'scheduler'")
    )
    # Полезная нагрузка результата: её UI показывает после succeeded.
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
