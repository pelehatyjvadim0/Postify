"""Preserve media versions and journal manual package changes.

Revision ID: 20260817_13
Revises: 20260817_12
"""

from alembic import op
import sqlalchemy as sa

revision = "20260817_13"
down_revision = "20260817_12"
branch_labels = None
depends_on = None


def _previous_terminal_constraint() -> str:
    return "(status = 'running' AND outcome IS NULL AND failure_code IS NULL AND finished_at IS NULL) OR (status = 'succeeded' AND btrim(outcome) <> '' AND failure_code IS NULL AND finished_at IS NOT NULL) OR (status = 'failed' AND outcome IS NULL AND btrim(failure_code) <> '' AND finished_at IS NOT NULL AND ((operation = 'run_once' AND failure_code = 'run_once_failed') OR (operation = 'publish_once' AND failure_code = 'publish_once_failed') OR (operation = 'load_more' AND failure_code = 'load_more_failed') OR (operation = 'retry_analysis' AND failure_code = 'retry_analysis_failed') OR (operation = 'return_to_analysis' AND failure_code = 'return_to_analysis_failed')))"


def upgrade() -> None:
    op.create_table("content_package_media_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), sa.ForeignKey("content_projects.id"), nullable=False),
        sa.Column("package_id", sa.BigInteger(), sa.ForeignKey("content_packages.id"), nullable=False),
        sa.Column("media_path", sa.Text(), nullable=False), sa.Column("media_mime", sa.String()),
        sa.Column("media_source_type", sa.String()), sa.Column("media_source_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index(
        "ix_content_package_media_versions_project_package",
        "content_package_media_versions",
        ["project_id", "package_id"],
    )
    op.drop_constraint("ck_operation_runs_operation", "operation_runs", type_="check")
    op.drop_constraint("ck_operation_runs_terminal_fields", "operation_runs", type_="check")
    op.create_check_constraint("ck_operation_runs_operation", "operation_runs", "operation IN ('run_once','publish_once','load_more','retry_analysis','return_to_analysis','regenerate_post','replace_media')")
    op.create_check_constraint("ck_operation_runs_terminal_fields", "operation_runs", "(status = 'running' AND outcome IS NULL AND failure_code IS NULL AND finished_at IS NULL) OR (status = 'succeeded' AND btrim(outcome) <> '' AND failure_code IS NULL AND finished_at IS NOT NULL) OR (status = 'failed' AND outcome IS NULL AND btrim(failure_code) <> '' AND finished_at IS NOT NULL AND ((operation = 'run_once' AND failure_code = 'run_once_failed') OR (operation = 'publish_once' AND failure_code = 'publish_once_failed') OR (operation = 'load_more' AND failure_code = 'load_more_failed') OR (operation = 'retry_analysis' AND failure_code = 'retry_analysis_failed') OR (operation = 'return_to_analysis' AND failure_code = 'return_to_analysis_failed') OR (operation = 'regenerate_post' AND failure_code = 'regenerate_post_failed') OR (operation = 'replace_media' AND failure_code = 'replace_media_failed')))" )


def downgrade() -> None:
    op.drop_constraint("ck_operation_runs_terminal_fields", "operation_runs", type_="check")
    op.drop_constraint("ck_operation_runs_operation", "operation_runs", type_="check")
    op.create_check_constraint("ck_operation_runs_operation", "operation_runs", "operation IN ('run_once','publish_once','load_more','retry_analysis','return_to_analysis')")
    op.create_check_constraint(
        "ck_operation_runs_terminal_fields",
        "operation_runs",
        _previous_terminal_constraint(),
    )
    op.drop_table("content_package_media_versions")
