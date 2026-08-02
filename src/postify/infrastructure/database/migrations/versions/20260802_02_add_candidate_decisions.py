"""Добавить неизменяемый журнал решений кандидатов.

Revision ID: 20260802_02
Revises: 20260801_01
Create Date: 2026-08-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260802_02"
down_revision = "20260801_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_decisions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("signals", postgresql.JSONB(), nullable=False),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["candidates.id"], name="fk_candidate_decisions_candidate_id_candidates"
        ),
        sa.UniqueConstraint("candidate_id", name="uq_candidate_decisions_candidate_id"),
        sa.CheckConstraint("status IN ('selected', 'rejected')", name="ck_candidate_decisions_status"),
    )


def downgrade() -> None:
    op.drop_table("candidate_decisions")
