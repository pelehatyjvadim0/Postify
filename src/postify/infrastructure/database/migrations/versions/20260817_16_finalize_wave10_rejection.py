"""Allow reasonless package-rejection history rows.

Revision ID: 20260817_16
Revises: 20260817_15
"""

from alembic import op
import sqlalchemy as sa


revision = "20260817_16"
down_revision = "20260817_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "content_package_status_history",
        "reason",
        existing_type=sa.String(),
        nullable=True,
    )
    op.add_column("content_packages", sa.Column("previous_package_id", sa.BigInteger()))
    op.create_unique_constraint(
        "uq_content_packages_project_id_id",
        "content_packages",
        ["project_id", "id"],
    )
    op.create_foreign_key(
        "fk_content_packages_project_previous_package",
        "content_packages",
        "content_packages",
        ["project_id", "previous_package_id"],
        ["project_id", "id"],
    )
    op.drop_constraint(
        "content_package_media_versions_package_id_fkey",
        "content_package_media_versions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_content_package_media_versions_project_package",
        "content_package_media_versions",
        "content_packages",
        ["project_id", "package_id"],
        ["project_id", "id"],
    )
    op.add_column("operation_runs", sa.Column("codex_model", sa.String()))
    op.add_column(
        "operation_runs", sa.Column("codex_reasoning_effort", sa.String())
    )
    op.add_column(
        "operation_runs",
        sa.Column(
            "materials_taken", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "operation_runs",
        sa.Column(
            "packages_created", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.create_check_constraint(
        "ck_content_daily_usage_nonnegative",
        "content_daily_usage",
        "analyses_started >= 0 AND packages_created >= 0 "
        "AND manual_analyses_started >= 0 AND manual_packages_created >= 0",
    )
    op.create_check_constraint(
        "ck_operation_runs_metadata",
        "operation_runs",
        "materials_taken >= 0 AND packages_created >= 0 AND "
        "((codex_model IS NULL AND codex_reasoning_effort IS NULL) OR "
        "(btrim(codex_model) <> '' AND codex_reasoning_effort IN "
        "('low','medium','high','xhigh','max')))",
    )
    op.create_check_constraint(
        "ck_operation_runs_outcome",
        "operation_runs",
        "status <> 'succeeded' OR "
        "(operation IN ('run_once','manual_search') AND outcome = 'completed') OR "
        "(operation IN ('load_more','retry_analysis','return_to_analysis',"
        "'regenerate_post','replace_media') AND outcome IN ('completed','empty')) OR "
        "(operation IN ('publish_once','publish_now','retry_delivery') AND outcome IN "
        "('empty','published','cleanup_completed','cleanup_pending','retryable',"
        "'failed','uncertain'))",
    )


def downgrade() -> None:
    op.drop_constraint("ck_operation_runs_outcome", "operation_runs", type_="check")
    op.drop_constraint("ck_operation_runs_metadata", "operation_runs", type_="check")
    op.drop_constraint(
        "ck_content_daily_usage_nonnegative", "content_daily_usage", type_="check"
    )
    op.drop_column("operation_runs", "packages_created")
    op.drop_column("operation_runs", "materials_taken")
    op.drop_column("operation_runs", "codex_reasoning_effort")
    op.drop_column("operation_runs", "codex_model")
    op.drop_constraint(
        "fk_content_package_media_versions_project_package",
        "content_package_media_versions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "content_package_media_versions_package_id_fkey",
        "content_package_media_versions",
        "content_packages",
        ["package_id"],
        ["id"],
    )
    op.drop_constraint(
        "fk_content_packages_project_previous_package",
        "content_packages",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_content_packages_project_id_id", "content_packages", type_="unique"
    )
    op.drop_column("content_packages", "previous_package_id")
    op.execute(
        "UPDATE content_package_status_history SET reason = 'review' WHERE reason IS NULL"
    )
    op.alter_column(
        "content_package_status_history",
        "reason",
        existing_type=sa.String(),
        nullable=False,
    )
