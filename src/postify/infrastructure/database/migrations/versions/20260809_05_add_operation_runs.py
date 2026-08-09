"""Добавить долговечный журнал запусков Postify.

Revision ID: 20260809_05
Revises: 20260809_04
"""

from alembic import op
import sqlalchemy as sa

revision = "20260809_05"
down_revision = "20260809_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("outcome", sa.String()),
        sa.Column("failure_code", sa.String()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "operation IN ('run_once', 'publish_once')",
            name="ck_operation_runs_operation",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_operation_runs_status",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND outcome IS NULL AND failure_code IS NULL AND finished_at IS NULL) "
            "OR (status = 'succeeded' AND btrim(outcome) <> '' AND failure_code IS NULL AND finished_at IS NOT NULL) "
            "OR (status = 'failed' AND outcome IS NULL AND btrim(failure_code) <> '' AND finished_at IS NOT NULL "
            "AND ((operation = 'run_once' AND failure_code = 'run_once_failed') "
            "OR (operation = 'publish_once' AND failure_code = 'publish_once_failed')))",
            name="ck_operation_runs_terminal_fields",
        ),
    )


def downgrade() -> None:
    op.drop_table("operation_runs")
