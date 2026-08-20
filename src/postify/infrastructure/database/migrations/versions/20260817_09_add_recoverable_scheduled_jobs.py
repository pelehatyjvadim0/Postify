"""Добавить маршрутизацию слотов и восстанавливаемые задания планировщика.

Revision ID: 20260817_09
Revises: 20260813_08
"""

from alembic import op
import sqlalchemy as sa


revision = "20260817_09"
down_revision = "20260813_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("pk_schedule_slot_claims", "schedule_slot_claims", type_="primary")
    op.add_column("schedule_slot_claims", sa.Column("route_id", sa.BigInteger()))
    op.create_foreign_key(
        "fk_schedule_slot_claims_project_route",
        "schedule_slot_claims",
        "publication_routes",
        ["project_id", "route_id"],
        ["project_id", "id"],
    )
    op.create_index(
        "uq_schedule_slot_claims_route_slot",
        "schedule_slot_claims",
        ["project_id", "kind", "scheduled_for", sa.text("COALESCE(route_id, 0)")],
        unique=True,
    )
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("route_id", sa.BigInteger()),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("operation_run_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('run_once','publish_once')", name="ck_scheduled_jobs_kind"
        ),
        sa.CheckConstraint(
            "status IN ('queued','leased','succeeded','failed')",
            name="ck_scheduled_jobs_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["content_projects.id"], name="fk_scheduled_jobs_project"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "route_id"],
            ["publication_routes.project_id", "publication_routes.id"],
            name="fk_scheduled_jobs_project_route",
        ),
        sa.ForeignKeyConstraint(
            ["operation_run_id"], ["operation_runs.id"], name="fk_scheduled_jobs_operation_run"
        ),
    )


def downgrade() -> None:
    op.drop_table("scheduled_jobs")
    op.drop_index("uq_schedule_slot_claims_route_slot", table_name="schedule_slot_claims")
    op.drop_constraint(
        "fk_schedule_slot_claims_project_route", "schedule_slot_claims", type_="foreignkey"
    )
    op.drop_column("schedule_slot_claims", "route_id")
    op.create_primary_key(
        "pk_schedule_slot_claims",
        "schedule_slot_claims",
        ["project_id", "kind", "scheduled_for"],
    )
