"""Allow the explicitly manual search operation in the journal.

Revision ID: 20260817_15
Revises: 20260817_14
"""
from alembic import op

revision = "20260817_15"
down_revision = "20260817_14"
branch_labels = None
depends_on = None


def _previous_terminal_constraint() -> str:
    return "(status = 'running' AND outcome IS NULL AND failure_code IS NULL AND finished_at IS NULL) OR (status = 'succeeded' AND btrim(outcome) <> '' AND failure_code IS NULL AND finished_at IS NOT NULL) OR (status = 'failed' AND outcome IS NULL AND btrim(failure_code) <> '' AND finished_at IS NOT NULL AND ((operation = 'run_once' AND failure_code = 'run_once_failed') OR (operation = 'publish_once' AND failure_code = 'publish_once_failed') OR (operation = 'load_more' AND failure_code = 'load_more_failed') OR (operation = 'retry_analysis' AND failure_code = 'retry_analysis_failed') OR (operation = 'return_to_analysis' AND failure_code = 'return_to_analysis_failed') OR (operation = 'regenerate_post' AND failure_code = 'regenerate_post_failed') OR (operation = 'replace_media' AND failure_code = 'replace_media_failed') OR (operation = 'publish_now' AND failure_code = 'publish_now_failed') OR (operation = 'retry_delivery' AND failure_code = 'retry_delivery_failed')))"


def upgrade() -> None:
    op.drop_constraint("ck_operation_runs_operation", "operation_runs", type_="check")
    op.drop_constraint("ck_operation_runs_terminal_fields", "operation_runs", type_="check")
    op.create_check_constraint("ck_operation_runs_operation", "operation_runs", "operation IN ('run_once','publish_once','load_more','retry_analysis','return_to_analysis','regenerate_post','replace_media','publish_now','retry_delivery','manual_search')")
    op.create_check_constraint("ck_operation_runs_terminal_fields", "operation_runs", "(status = 'running' AND outcome IS NULL AND failure_code IS NULL AND finished_at IS NULL) OR (status = 'succeeded' AND btrim(outcome) <> '' AND failure_code IS NULL AND finished_at IS NOT NULL) OR (status = 'failed' AND outcome IS NULL AND btrim(failure_code) <> '' AND finished_at IS NOT NULL AND ((operation = 'run_once' AND failure_code = 'run_once_failed') OR (operation = 'publish_once' AND failure_code = 'publish_once_failed') OR (operation = 'load_more' AND failure_code = 'load_more_failed') OR (operation = 'retry_analysis' AND failure_code = 'retry_analysis_failed') OR (operation = 'return_to_analysis' AND failure_code = 'return_to_analysis_failed') OR (operation = 'regenerate_post' AND failure_code = 'regenerate_post_failed') OR (operation = 'replace_media' AND failure_code = 'replace_media_failed') OR (operation = 'publish_now' AND failure_code = 'publish_now_failed') OR (operation = 'retry_delivery' AND failure_code = 'retry_delivery_failed') OR (operation = 'manual_search' AND failure_code = 'manual_search_failed')))" )


def downgrade() -> None:
    op.drop_constraint("ck_operation_runs_terminal_fields", "operation_runs", type_="check")
    op.drop_constraint("ck_operation_runs_operation", "operation_runs", type_="check")
    op.create_check_constraint("ck_operation_runs_operation", "operation_runs", "operation IN ('run_once','publish_once','load_more','retry_analysis','return_to_analysis','regenerate_post','replace_media','publish_now','retry_delivery')")
    op.create_check_constraint(
        "ck_operation_runs_terminal_fields",
        "operation_runs",
        _previous_terminal_constraint(),
    )
