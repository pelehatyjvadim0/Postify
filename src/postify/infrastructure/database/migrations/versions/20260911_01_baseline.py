"""Стартовая схема SMM-агента.

Старый контур импорта материалов снесён вместе с его миграциями: данные
продакшена по решению Р10 стираются, поэтому цепочка начинается заново.
Схема содержит только то, что переживает переработку: проект и его рубрики,
канал, посты, доставки, журнал операций и расписание.

Каждый следующий трек добавляет свою ревизию поверх этой.

Revision ID: 20260911_01
Revises: None
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260911_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Расширение нужно треку пула изображений; включаем сразу, чтобы образ БД
    # и права проверялись один раз, а не в середине работ.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "content_projects",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "project_rubrics",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("content_projects.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "id", name="uq_project_rubrics_project_id_id"),
        sa.UniqueConstraint(
            "project_id", "name", name="uq_project_rubrics_project_id_name"
        ),
    )

    op.create_table(
        "channel_connections",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("content_projects.id"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("encrypted_secret", sa.Text()),
        sa.Column("connection_status", sa.String(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # Проект равен одному каналу.
        sa.UniqueConstraint("project_id", name="uq_channel_connections_project_id"),
        sa.UniqueConstraint(
            "project_id", "id", name="uq_channel_connections_project_id_id"
        ),
    )

    op.create_table(
        "posts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("content_projects.id"),
            nullable=False,
        ),
        sa.Column("post_text", sa.Text(), nullable=False),
        sa.Column("media_path", sa.Text()),
        sa.Column("media_mime", sa.String()),
        sa.Column("media_deleted_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "generation",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "id", name="uq_posts_project_id_id"),
        sa.CheckConstraint(
            "status IN ('generating','needs_review','approved','rejected','failed','published')",
            name="ck_posts_status",
        ),
    )
    op.create_index(
        "ix_posts_due",
        "posts",
        ["scheduled_at", "id"],
        postgresql_where=sa.text("status = 'approved'"),
    )

    op.create_table(
        "post_status_history",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("content_projects.id"),
            nullable=False,
        ),
        sa.Column("post_id", sa.BigInteger(), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "operation_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("content_projects.id"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("outcome", sa.String()),
        sa.Column("failure_code", sa.String()),
        sa.Column("mode", sa.String(), nullable=False, server_default=sa.text("'automatic'")),
        sa.Column("actor", sa.String(), nullable=False, server_default=sa.text("'scheduler'")),
        sa.Column(
            "result",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "operation IN ('generate_post','regenerate_post','publish_once',"
            "'retry_delivery','derive_rules','caption_media')",
            name="ck_operation_runs_operation",
        ),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')",
            name="ck_operation_runs_status",
        ),
        sa.CheckConstraint(
            "(mode = 'automatic' AND actor = 'scheduler')"
            " OR (mode = 'manual' AND actor = 'user')",
            name="ck_operation_runs_context",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND outcome IS NULL AND failure_code IS NULL"
            " AND finished_at IS NULL)"
            " OR (status = 'succeeded' AND btrim(outcome) <> '' AND failure_code IS NULL"
            " AND finished_at IS NOT NULL)"
            " OR (status = 'failed' AND outcome IS NULL AND btrim(failure_code) <> ''"
            " AND finished_at IS NOT NULL AND failure_code = operation || '_failed')",
            name="ck_operation_runs_terminal_fields",
        ),
    )
    op.create_index(
        "uq_operation_runs_active_project_operation",
        "operation_runs",
        ["project_id", "operation"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("content_projects.id"),
            nullable=False,
        ),
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger()),
        sa.Column(
            "channel_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.BigInteger()),
        sa.Column("sending_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("media_deleted_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String()),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("post_id", name="uq_deliveries_post_id"),
        sa.CheckConstraint(
            "status IN ('sending','retryable','published','failed','uncertain')",
            name="ck_deliveries_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "post_id"],
            ["posts.project_id", "posts.id"],
            name="fk_deliveries_project_post",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "channel_id"],
            ["channel_connections.project_id", "channel_connections.id"],
            name="fk_deliveries_project_channel",
        ),
    )

    op.create_table(
        "delivery_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("content_projects.id"),
            nullable=False,
        ),
        sa.Column(
            "delivery_id",
            sa.BigInteger(),
            sa.ForeignKey("deliveries.id"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("code", sa.String()),
        sa.Column("reason", sa.Text()),
        sa.Column("message_id", sa.BigInteger()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "delivery_id",
            "attempt_no",
            name="uq_delivery_attempts_delivery_id_attempt_no",
        ),
        sa.CheckConstraint(
            "outcome IN ('retryable','published','failed','uncertain')",
            name="ck_delivery_attempts_outcome",
        ),
    )

    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("content_projects.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("post_id", sa.BigInteger()),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "operation_run_id",
            sa.BigInteger(),
            sa.ForeignKey("operation_runs.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('generate_post','publish_once')", name="ck_scheduled_jobs_kind"
        ),
        sa.CheckConstraint(
            "status IN ('queued','leased','succeeded','failed')",
            name="ck_scheduled_jobs_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "post_id"],
            ["posts.project_id", "posts.id"],
            name="fk_scheduled_jobs_project_post",
        ),
    )

    op.create_table(
        "schedule_slot_claims",
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("content_projects.id"),
            primary_key=True,
        ),
        sa.Column("kind", sa.String(), primary_key=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("post_id", sa.BigInteger()),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "kind IN ('generate_post','publish_once')",
            name="ck_schedule_slot_claims_kind",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "post_id"],
            ["posts.project_id", "posts.id"],
            name="fk_schedule_slot_claims_project_post",
        ),
    )
    op.create_index(
        "uq_schedule_slot_claims_slot",
        "schedule_slot_claims",
        ["project_id", "kind", "scheduled_for", sa.text("COALESCE(post_id, 0)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("schedule_slot_claims")
    op.drop_table("scheduled_jobs")
    op.drop_table("delivery_attempts")
    op.drop_table("deliveries")
    op.drop_table("operation_runs")
    op.drop_table("post_status_history")
    op.drop_table("posts")
    op.drop_table("channel_connections")
    op.drop_table("project_rubrics")
    op.drop_table("content_projects")
