"""Добавляет очередь и пакеты контента.

Revision ID: 20260808_03
Revises: 20260802_02
"""

from alembic import op
import sqlalchemy as sa

revision = "20260808_03"
down_revision = "20260802_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_quota_state",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("fresh_credit", sa.Integer(), nullable=False),
        sa.Column("reserve_credit", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "content_daily_usage",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("analyses_started", sa.Integer(), nullable=False),
        sa.Column("packages_created", sa.Integer(), nullable=False),
    )
    op.create_table(
        "content_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.BigInteger(),
            sa.ForeignKey("candidates.id"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("article_title", sa.Text()),
        sa.Column("article_text", sa.Text()),
        sa.Column("analysis", sa.Text()),
        sa.Column("failure_code", sa.String()),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "candidate_id",
            "attempt_no",
            name="uq_content_attempts_candidate_id_attempt_no",
        ),
    )
    op.create_table(
        "content_packages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "attempt_id",
            sa.BigInteger(),
            sa.ForeignKey("content_attempts.id"),
            nullable=False,
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("analysis", sa.Text(), nullable=False),
        sa.Column("post_text", sa.Text(), nullable=False),
        sa.Column("media_path", sa.Text()),
        sa.Column("media_mime", sa.String()),
        sa.Column("media_source_type", sa.String()),
        sa.Column("media_source_url", sa.Text()),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("media_deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("attempt_id", name="uq_content_packages_attempt_id"),
    )
    op.create_table(
        "content_package_status_history",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "package_id",
            sa.BigInteger(),
            sa.ForeignKey("content_packages.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("content_package_status_history")
    op.drop_table("content_packages")
    op.drop_table("content_attempts")
    op.drop_table("content_daily_usage")
    op.drop_table("content_quota_state")
