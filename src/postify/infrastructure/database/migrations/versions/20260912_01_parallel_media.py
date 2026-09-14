"""Разрешить независимые фоновые описания изображений."""
from alembic import op
import sqlalchemy as sa

revision = "20260912_01"
down_revision = "20260911_06"
branch_labels = None
depends_on = None

INDEX = "uq_operation_runs_active_project_operation"


def upgrade() -> None:
    op.drop_index(INDEX, table_name="operation_runs")
    op.create_index(
        INDEX, "operation_runs", ["project_id", "operation"], unique=True,
        postgresql_where=sa.text("status = 'running' AND operation <> 'caption_media'"),
    )


def downgrade() -> None:
    # Перед откатом нужно дождаться завершения фоновых описаний.
    op.drop_index(INDEX, table_name="operation_runs")
    op.create_index(
        INDEX, "operation_runs", ["project_id", "operation"], unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
