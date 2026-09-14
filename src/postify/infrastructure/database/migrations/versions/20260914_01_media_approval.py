"""Блокировка повторов по одобрению, настройка проекта."""
from alembic import op
import sqlalchemy as sa
revision = "20260914_01"
down_revision = "20260912_01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("content_projects", sa.Column("media_reuse_blocked", sa.Boolean(), nullable=False, server_default=sa.true()))
    # Старые черновики потребляли фото ещё при генерации. Сохраняем только
    # использования постов, у которых действительно было одобрение/публикация.
    op.execute("DELETE FROM media_usages u WHERE NOT EXISTS (SELECT 1 FROM post_status_history h WHERE h.post_id=u.post_id AND h.status IN ('approved','published'))")
    op.execute("UPDATE media_assets a SET use_count=(SELECT count(*) FROM media_usages u WHERE u.asset_id=a.id),last_used_at=(SELECT max(used_at) FROM media_usages u WHERE u.asset_id=a.id)")


def downgrade():
    op.drop_column("content_projects", "media_reuse_blocked")
