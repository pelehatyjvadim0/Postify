"""Persist the initial Telegram history cutoff even when no text was imported."""
from alembic import op
import sqlalchemy as sa


revision = "20260905_18"
down_revision = "20260905_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_source_state",
        sa.Column("project_id", sa.BigInteger(), primary_key=True),
        sa.Column("source_connection_id", sa.BigInteger(), primary_key=True),
        sa.Column("group_id", sa.String(), primary_key=True),
        sa.Column("initial_after_message_id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("initial_after_message_id >= 0", name="ck_telegram_source_state_initial_id"),
        sa.ForeignKeyConstraint(
            ["project_id", "source_connection_id"],
            ["source_connections.project_id", "source_connections.id"],
            name="fk_telegram_source_state_project_source",
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("telegram_source_state")
