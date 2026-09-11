"""Правила проекта и отчёты слоёв проверки."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260911_06"
down_revision = "20260911_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), sa.ForeignKey("content_projects.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False, server_default="block"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("origin", sa.String(), nullable=False, server_default="manual"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("severity IN ('block','warn')", name="ck_project_rules_severity"),
        sa.CheckConstraint("origin IN ('derived','manual')", name="ck_project_rules_origin"),
        sa.UniqueConstraint("project_id", "position", name="uq_project_rules_position"),
    )
    op.create_table(
        "validation_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("post_id", sa.BigInteger(), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("layer", sa.String(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("post_id", "iteration", "layer", name="uq_validation_reports_post_iteration_layer"),
    )


def downgrade() -> None:
    op.drop_table("validation_reports")
    op.drop_table("project_rules")
