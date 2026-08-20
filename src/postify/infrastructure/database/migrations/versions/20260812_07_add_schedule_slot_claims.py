"""Добавить долговечные claims слотов планировщика.

Revision ID: 20260812_07
Revises: 20260812_06
"""

from alembic import op
import sqlalchemy as sa


revision = "20260812_07"
down_revision = "20260812_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_slot_claims",
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "kind IN ('run_once','publish_once')",
            name="ck_schedule_slot_claims_kind",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["content_projects.id"],
            name="fk_schedule_slot_claims_project_id_content_projects",
        ),
        sa.PrimaryKeyConstraint(
            "project_id",
            "kind",
            "scheduled_for",
            name="pk_schedule_slot_claims",
        ),
    )


def downgrade() -> None:
    op.drop_table("schedule_slot_claims")
