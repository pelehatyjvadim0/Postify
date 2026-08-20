"""Separate manual usage and record server-selected execution context.

Revision ID: 20260817_11
Revises: 20260817_10
"""

from alembic import op
import sqlalchemy as sa

revision = "20260817_11"
down_revision = "20260817_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_daily_usage", sa.Column("manual_analyses_started", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("content_daily_usage", sa.Column("manual_packages_created", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("operation_runs", sa.Column("mode", sa.String(), nullable=False, server_default="automatic"))
    op.add_column("operation_runs", sa.Column("actor", sa.String(), nullable=False, server_default="scheduler"))
    op.drop_constraint("ck_operation_runs_operation", "operation_runs", type_="check")
    op.drop_constraint("ck_operation_runs_terminal_fields", "operation_runs", type_="check")
    op.create_check_constraint("ck_operation_runs_operation", "operation_runs", "operation IN ('run_once','publish_once','load_more')")
    op.create_check_constraint("ck_operation_runs_context", "operation_runs", "(mode = 'automatic' AND actor = 'scheduler') OR (mode = 'manual' AND actor = 'ui')")
    op.create_check_constraint("ck_operation_runs_terminal_fields", "operation_runs", "(status = 'running' AND outcome IS NULL AND failure_code IS NULL AND finished_at IS NULL) OR (status = 'succeeded' AND btrim(outcome) <> '' AND failure_code IS NULL AND finished_at IS NOT NULL) OR (status = 'failed' AND outcome IS NULL AND btrim(failure_code) <> '' AND finished_at IS NOT NULL AND ((operation = 'run_once' AND failure_code = 'run_once_failed') OR (operation = 'publish_once' AND failure_code = 'publish_once_failed') OR (operation = 'load_more' AND failure_code = 'load_more_failed')))" )


def downgrade() -> None:
    op.drop_constraint("ck_operation_runs_terminal_fields", "operation_runs", type_="check")
    op.drop_constraint("ck_operation_runs_context", "operation_runs", type_="check")
    op.drop_constraint("ck_operation_runs_operation", "operation_runs", type_="check")
    op.create_check_constraint("ck_operation_runs_operation", "operation_runs", "operation IN ('run_once','publish_once')")
    op.create_check_constraint(
        "ck_operation_runs_terminal_fields",
        "operation_runs",
        "(status = 'running' AND outcome IS NULL AND failure_code IS NULL AND finished_at IS NULL) OR "
        "(status = 'succeeded' AND btrim(outcome) <> '' AND failure_code IS NULL AND finished_at IS NOT NULL) OR "
        "(status = 'failed' AND outcome IS NULL AND btrim(failure_code) <> '' AND finished_at IS NOT NULL AND "
        "((operation = 'run_once' AND failure_code = 'run_once_failed') OR "
        "(operation = 'publish_once' AND failure_code = 'publish_once_failed')))"
    )
    op.drop_column("operation_runs", "actor")
    op.drop_column("operation_runs", "mode")
    op.drop_column("content_daily_usage", "manual_packages_created")
    op.drop_column("content_daily_usage", "manual_analyses_started")
