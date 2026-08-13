"""Добавить production-инварианты проектов.

Revision ID: 20260813_08
Revises: 20260812_07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260813_08"
down_revision = "20260812_07"
branch_labels = None
depends_on = None


PROJECT_TABLES = (
    "candidates",
    "candidate_decisions",
    "content_quota_state",
    "content_daily_usage",
    "content_attempts",
    "content_packages",
    "content_package_status_history",
    "deliveries",
    "delivery_attempts",
    "operation_runs",
)


def upgrade() -> None:
    op.create_index(
        "uq_operation_runs_active_project_operation",
        "operation_runs",
        ["project_id", "operation"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    for table in PROJECT_TABLES:
        op.alter_column(table, "project_id", server_default=None)

    for table in (
        "content_formats",
        "channel_connections",
        "calls_to_action",
        "publication_routes",
    ):
        op.create_unique_constraint(
            f"uq_{table}_project_id_id", table, ["project_id", "id"]
        )

    for name in (
        "fk_publication_routes_format_id_content_formats",
        "fk_publication_routes_channel_id_channel_connections",
        "fk_publication_routes_cta_id_calls_to_action",
    ):
        op.drop_constraint(name, "publication_routes", type_="foreignkey")
    op.create_foreign_key(
        "fk_publication_routes_project_format",
        "publication_routes",
        "content_formats",
        ["project_id", "format_id"],
        ["project_id", "id"],
    )
    op.create_foreign_key(
        "fk_publication_routes_project_channel",
        "publication_routes",
        "channel_connections",
        ["project_id", "channel_id"],
        ["project_id", "id"],
    )
    op.create_foreign_key(
        "fk_publication_routes_project_cta",
        "publication_routes",
        "calls_to_action",
        ["project_id", "cta_id"],
        ["project_id", "id"],
    )

    op.drop_constraint(
        "fk_deliveries_route_id_publication_routes",
        "deliveries",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_deliveries_channel_id_channel_connections",
        "deliveries",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_deliveries_project_route",
        "deliveries",
        "publication_routes",
        ["project_id", "route_id"],
        ["project_id", "id"],
    )
    op.create_foreign_key(
        "fk_deliveries_project_channel",
        "deliveries",
        "channel_connections",
        ["project_id", "channel_id"],
        ["project_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_deliveries_project_channel", "deliveries", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_deliveries_project_route", "deliveries", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_deliveries_route_id_publication_routes",
        "deliveries",
        "publication_routes",
        ["route_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_deliveries_channel_id_channel_connections",
        "deliveries",
        "channel_connections",
        ["channel_id"],
        ["id"],
    )

    for name in (
        "fk_publication_routes_project_cta",
        "fk_publication_routes_project_channel",
        "fk_publication_routes_project_format",
    ):
        op.drop_constraint(name, "publication_routes", type_="foreignkey")
    op.create_foreign_key(
        "fk_publication_routes_format_id_content_formats",
        "publication_routes",
        "content_formats",
        ["format_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_publication_routes_channel_id_channel_connections",
        "publication_routes",
        "channel_connections",
        ["channel_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_publication_routes_cta_id_calls_to_action",
        "publication_routes",
        "calls_to_action",
        ["cta_id"],
        ["id"],
    )
    for table in reversed(
        (
            "content_formats",
            "channel_connections",
            "calls_to_action",
            "publication_routes",
        )
    ):
        op.drop_constraint(
            f"uq_{table}_project_id_id", table, type_="unique"
        )
    for table in PROJECT_TABLES:
        op.alter_column(table, "project_id", server_default=sa.text("1"))
    op.drop_index(
        "uq_operation_runs_active_project_operation",
        table_name="operation_runs",
    )
