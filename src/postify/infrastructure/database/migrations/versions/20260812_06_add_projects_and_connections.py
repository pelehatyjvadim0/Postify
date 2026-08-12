"""Добавить проекты и универсальные подключения.

Revision ID: 20260812_06
Revises: 20260809_05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260812_06"
down_revision = "20260809_05"
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


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "content_projects",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column(
            "configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        *_timestamps(),
    )
    op.execute(
        """
        INSERT INTO content_projects
        (id,name,topic,language,audience,timezone,configuration,created_at,updated_at)
        VALUES
        (1,'Технологии просто','Тема проекта','ru','Аудитория проекта',
         'Europe/Moscow','{}'::jsonb,now(),now())
        """
    )

    op.create_table(
        "source_connections",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("schedule", sa.String(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["content_projects.id"],
            name="fk_source_connections_project_id_content_projects",
        ),
        sa.UniqueConstraint(
            "project_id", "name", name="uq_source_connections_project_id_name"
        ),
    )
    op.create_table(
        "content_formats",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["content_projects.id"],
            name="fk_content_formats_project_id_content_projects",
        ),
        sa.UniqueConstraint(
            "project_id", "name", name="uq_content_formats_project_id_name"
        ),
    )
    op.create_table(
        "calls_to_action",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("link_mode", sa.String(), nullable=False),
        sa.Column("custom_url", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["content_projects.id"],
            name="fk_calls_to_action_project_id_content_projects",
        ),
        sa.UniqueConstraint(
            "project_id", "name", name="uq_calls_to_action_project_id_name"
        ),
        sa.CheckConstraint(
            "link_mode IN ('none','source','custom')",
            name="ck_calls_to_action_link_mode",
        ),
        sa.CheckConstraint(
            "(link_mode = 'custom' AND custom_url IS NOT NULL) OR "
            "(link_mode <> 'custom' AND custom_url IS NULL)",
            name="ck_calls_to_action_custom_url",
        ),
    )
    op.create_table(
        "channel_connections",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("encrypted_secret", sa.Text()),
        sa.Column("connection_status", sa.String(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["content_projects.id"],
            name="fk_channel_connections_project_id_content_projects",
        ),
        sa.UniqueConstraint(
            "project_id", "name", name="uq_channel_connections_project_id_name"
        ),
    )
    op.create_table(
        "publication_routes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("format_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("cta_id", sa.BigInteger()),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("schedule", postgresql.JSONB(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["content_projects.id"],
            name="fk_publication_routes_project_id_content_projects",
        ),
        sa.ForeignKeyConstraint(
            ["format_id"],
            ["content_formats.id"],
            name="fk_publication_routes_format_id_content_formats",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channel_connections.id"],
            name="fk_publication_routes_channel_id_channel_connections",
        ),
        sa.ForeignKeyConstraint(
            ["cta_id"],
            ["calls_to_action.id"],
            name="fk_publication_routes_cta_id_calls_to_action",
        ),
        sa.UniqueConstraint(
            "project_id",
            "format_id",
            "channel_id",
            name="uq_publication_routes_project_format_channel",
        ),
    )

    op.rename_table("telegram_deliveries", "deliveries")
    op.rename_table("telegram_delivery_attempts", "delivery_attempts")
    constraint_renames = (
        ("deliveries", "uq_telegram_deliveries_package_id", "uq_deliveries_package_id"),
        ("deliveries", "fk_telegram_deliveries_package_id_content_packages", "fk_deliveries_package_id_content_packages"),
        ("deliveries", "ck_telegram_deliveries_status", "ck_deliveries_status"),
        ("delivery_attempts", "uq_telegram_delivery_attempts_delivery_id_attempt_no", "uq_delivery_attempts_delivery_id_attempt_no"),
        ("delivery_attempts", "fk_telegram_delivery_attempts_delivery_id_telegram_deliveries", "fk_delivery_attempts_delivery_id_deliveries"),
        ("delivery_attempts", "ck_telegram_delivery_attempts_outcome", "ck_delivery_attempts_outcome"),
    )
    for table, old, new in constraint_renames:
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old}" TO "{new}"')

    for table in PROJECT_TABLES:
        op.add_column(
            table,
            sa.Column(
                "project_id",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )
        op.create_foreign_key(
            f"fk_{table}_project_id_content_projects",
            table,
            "content_projects",
            ["project_id"],
            ["id"],
        )

    for table, old, new, columns in (
        (
            "candidates",
            "uq_candidates_source_name_source_id",
            "uq_candidates_project_source_name_source_id",
            ["project_id", "source_name", "source_id"],
        ),
        (
            "candidate_decisions",
            "uq_candidate_decisions_candidate_id",
            "uq_candidate_decisions_project_candidate_id",
            ["project_id", "candidate_id"],
        ),
        (
            "content_attempts",
            "uq_content_attempts_candidate_id_attempt_no",
            "uq_content_attempts_project_candidate_attempt",
            ["project_id", "candidate_id", "attempt_no"],
        ),
        (
            "content_packages",
            "uq_content_packages_attempt_id",
            "uq_content_packages_project_attempt_id",
            ["project_id", "attempt_id"],
        ),
    ):
        op.drop_constraint(old, table, type_="unique")
        op.create_unique_constraint(new, table, columns)

    op.drop_constraint("content_quota_state_pkey", "content_quota_state", type_="primary")
    op.create_primary_key(
        "pk_content_quota_state", "content_quota_state", ["project_id", "id"]
    )
    op.drop_constraint("content_daily_usage_pkey", "content_daily_usage", type_="primary")
    op.create_primary_key(
        "pk_content_daily_usage", "content_daily_usage", ["project_id", "day"]
    )

    op.add_column(
        "content_packages",
        sa.Column(
            "generation_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("deliveries", sa.Column("route_id", sa.BigInteger()))
    op.add_column("deliveries", sa.Column("channel_id", sa.BigInteger()))
    op.add_column(
        "deliveries",
        sa.Column(
            "channel_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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


def downgrade() -> None:
    op.drop_constraint(
        "fk_deliveries_channel_id_channel_connections", "deliveries", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_deliveries_route_id_publication_routes", "deliveries", type_="foreignkey"
    )
    op.drop_column("deliveries", "channel_snapshot")
    op.drop_column("deliveries", "channel_id")
    op.drop_column("deliveries", "route_id")
    op.drop_column("content_packages", "generation_snapshot")

    op.drop_constraint("pk_content_daily_usage", "content_daily_usage", type_="primary")
    op.create_primary_key("content_daily_usage_pkey", "content_daily_usage", ["day"])
    op.drop_constraint("pk_content_quota_state", "content_quota_state", type_="primary")
    op.create_primary_key("content_quota_state_pkey", "content_quota_state", ["id"])

    for table, current, restored, columns in (
        (
            "content_packages",
            "uq_content_packages_project_attempt_id",
            "uq_content_packages_attempt_id",
            ["attempt_id"],
        ),
        (
            "content_attempts",
            "uq_content_attempts_project_candidate_attempt",
            "uq_content_attempts_candidate_id_attempt_no",
            ["candidate_id", "attempt_no"],
        ),
        (
            "candidate_decisions",
            "uq_candidate_decisions_project_candidate_id",
            "uq_candidate_decisions_candidate_id",
            ["candidate_id"],
        ),
        (
            "candidates",
            "uq_candidates_project_source_name_source_id",
            "uq_candidates_source_name_source_id",
            ["source_name", "source_id"],
        ),
    ):
        op.drop_constraint(current, table, type_="unique")
        op.create_unique_constraint(restored, table, columns)

    for table in reversed(PROJECT_TABLES):
        op.drop_constraint(
            f"fk_{table}_project_id_content_projects", table, type_="foreignkey"
        )
        op.drop_column(table, "project_id")

    reverse_constraint_renames = (
        ("delivery_attempts", "ck_delivery_attempts_outcome", "ck_telegram_delivery_attempts_outcome"),
        ("delivery_attempts", "fk_delivery_attempts_delivery_id_deliveries", "fk_telegram_delivery_attempts_delivery_id_telegram_deliveries"),
        ("delivery_attempts", "uq_delivery_attempts_delivery_id_attempt_no", "uq_telegram_delivery_attempts_delivery_id_attempt_no"),
        ("deliveries", "ck_deliveries_status", "ck_telegram_deliveries_status"),
        ("deliveries", "fk_deliveries_package_id_content_packages", "fk_telegram_deliveries_package_id_content_packages"),
        ("deliveries", "uq_deliveries_package_id", "uq_telegram_deliveries_package_id"),
    )
    for table, old, new in reverse_constraint_renames:
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old}" TO "{new}"')
    op.rename_table("delivery_attempts", "telegram_delivery_attempts")
    op.rename_table("deliveries", "telegram_deliveries")

    op.drop_table("publication_routes")
    op.drop_table("channel_connections")
    op.drop_table("calls_to_action")
    op.drop_table("content_formats")
    op.drop_table("source_connections")
    op.drop_table("content_projects")

