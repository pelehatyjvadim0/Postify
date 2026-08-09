"""Добавить очередь Telegram-доставки.

Revision ID: 20260809_04
Revises: 20260808_03
"""

from alembic import op
import sqlalchemy as sa

revision = "20260809_04"
down_revision = "20260808_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("package_id", sa.BigInteger(), nullable=False),
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
        sa.ForeignKeyConstraint(["package_id"], ["content_packages.id"], name="fk_telegram_deliveries_package_id_content_packages"),
        sa.UniqueConstraint("package_id", name="uq_telegram_deliveries_package_id"),
        sa.CheckConstraint("status IN ('sending', 'retryable', 'published', 'failed', 'uncertain')", name="ck_telegram_deliveries_status"),
    )
    op.create_table(
        "telegram_delivery_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("delivery_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("code", sa.String()),
        sa.Column("reason", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_id", sa.BigInteger()),
        sa.ForeignKeyConstraint(["delivery_id"], ["telegram_deliveries.id"], name="fk_telegram_delivery_attempts_delivery_id_telegram_deliveries"),
        sa.UniqueConstraint("delivery_id", "attempt_no", name="uq_telegram_delivery_attempts_delivery_id_attempt_no"),
        sa.CheckConstraint("outcome IN ('retryable', 'published', 'failed', 'uncertain')", name="ck_telegram_delivery_attempts_outcome"),
    )


def downgrade() -> None:
    op.drop_table("telegram_delivery_attempts")
    op.drop_table("telegram_deliveries")
