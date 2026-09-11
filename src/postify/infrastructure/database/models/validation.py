from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from postify.infrastructure.database.models.base import Base


class ProjectRuleModel(Base):
    __tablename__ = "project_rules"
    __table_args__ = (
        CheckConstraint("severity IN ('block','warn')", name="ck_project_rules_severity"),
        CheckConstraint("origin IN ('derived','manual')", name="ck_project_rules_origin"),
        UniqueConstraint("project_id", "position", name="uq_project_rules_position"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("content_projects.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False, server_default="block")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    origin: Mapped[str] = mapped_column(String, nullable=False, server_default="manual")
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class ValidationReportModel(Base):
    __tablename__ = "validation_reports"
    __table_args__ = (UniqueConstraint("post_id", "iteration", "layer", name="uq_validation_reports_post_iteration_layer"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("posts.id"), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    layer: Mapped[str] = mapped_column(String, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
