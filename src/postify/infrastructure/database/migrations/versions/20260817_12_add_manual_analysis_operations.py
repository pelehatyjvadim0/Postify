"""Add journal kinds for manual analysis recovery.

Revision ID: 20260817_12
Revises: 20260817_11
"""

from alembic import op

revision = "20260817_12"
down_revision = "20260817_11"
branch_labels = None
depends_on = None


def _terminal_constraint() -> str:
    return "(status = 'running' AND outcome IS NULL AND failure_code IS NULL AND finished_at IS NULL) OR (status = 'succeeded' AND btrim(outcome) <> '' AND failure_code IS NULL AND finished_at IS NOT NULL) OR (status = 'failed' AND outcome IS NULL AND btrim(failure_code) <> '' AND finished_at IS NOT NULL AND ((operation = 'run_once' AND failure_code = 'run_once_failed') OR (operation = 'publish_once' AND failure_code = 'publish_once_failed') OR (operation = 'load_more' AND failure_code = 'load_more_failed') OR (operation = 'retry_analysis' AND failure_code = 'retry_analysis_failed') OR (operation = 'return_to_analysis' AND failure_code = 'return_to_analysis_failed')))"


def upgrade() -> None:
    op.drop_constraint("ck_operation_runs_operation", "operation_runs", type_="check")
    op.drop_constraint("ck_operation_runs_terminal_fields", "operation_runs", type_="check")
    op.create_check_constraint("ck_operation_runs_operation", "operation_runs", "operation IN ('run_once','publish_once','load_more','retry_analysis','return_to_analysis')")
    op.create_check_constraint("ck_operation_runs_terminal_fields", "operation_runs", _terminal_constraint())


def downgrade() -> None:
    op.drop_constraint("ck_operation_runs_terminal_fields", "operation_runs", type_="check")
    op.drop_constraint("ck_operation_runs_operation", "operation_runs", type_="check")
    op.create_check_constraint("ck_operation_runs_operation", "operation_runs", "operation IN ('run_once','publish_once','load_more')")
    op.create_check_constraint("ck_operation_runs_terminal_fields", "operation_runs", "(status = 'running' AND outcome IS NULL AND failure_code IS NULL AND finished_at IS NULL) OR (status = 'succeeded' AND btrim(outcome) <> '' AND failure_code IS NULL AND finished_at IS NOT NULL) OR (status = 'failed' AND outcome IS NULL AND btrim(failure_code) <> '' AND finished_at IS NOT NULL AND ((operation = 'run_once' AND failure_code = 'run_once_failed') OR (operation = 'publish_once' AND failure_code = 'publish_once_failed') OR (operation = 'load_more' AND failure_code = 'load_more_failed')))" )
