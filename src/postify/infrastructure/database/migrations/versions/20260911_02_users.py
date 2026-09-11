"""Пользователи, запросы на вход, сессии и владение проектом.

Вход переезжает с общего пароля на Telegram-бота, поэтому появляются таблицы
``users``, ``login_requests``, ``user_sessions`` и ``user_settings``.
Запросы на вход и сессии хранятся в базе, а не в памяти процесса: перезапуск
контейнера не должен разлогинивать пользователей.

Здесь же ``content_projects.owner_id``: проект принадлежит одному
пользователю, и зависимость владения фильтрует по этой колонке. Колонка
создаётся ``NOT NULL`` без значения по умолчанию — по решению Р10 данных в
базе нет.

Revision ID: 20260911_02
Revises: 20260911_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260911_02"
down_revision = "20260911_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        # Строкой: id Telegram шире int32 и везде сравнивается как строка.
        sa.Column("telegram_user_id", sa.String(), nullable=False),
        sa.Column("telegram_username", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("telegram_user_id", name="uq_users_telegram_user_id"),
    )

    op.create_table(
        "login_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("telegram_token", sa.String(), nullable=False),
        sa.Column("browser_token", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("telegram_user_id", sa.String()),
        sa.Column("telegram_username", sa.String()),
        sa.Column("display_name", sa.String()),
        sa.Column("ip", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "telegram_token", name="uq_login_requests_telegram_token"
        ),
        sa.UniqueConstraint("browser_token", name="uq_login_requests_browser_token"),
        sa.CheckConstraint(
            "status IN ('pending','confirmation','approved','denied')",
            name="ck_login_requests_status",
        ),
    )
    # Лимит попыток с одного IP и уборка истёкших читают именно эти колонки.
    op.create_index("ix_login_requests_ip_created_at", "login_requests", ["ip", "created_at"])
    op.create_index("ix_login_requests_expires_at", "login_requests", ["expires_at"])

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Только хеш: дамп базы не даёт войти чужой сессией.
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])

    op.create_table(
        "user_settings",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("common_prompt", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column(
        "content_projects",
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
    )
    op.create_foreign_key(
        "fk_content_projects_owner_id_users",
        "content_projects",
        "users",
        ["owner_id"],
        ["id"],
    )
    op.create_index("ix_content_projects_owner_id", "content_projects", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_content_projects_owner_id", table_name="content_projects")
    op.drop_constraint(
        "fk_content_projects_owner_id_users", "content_projects", type_="foreignkey"
    )
    op.drop_column("content_projects", "owner_id")
    op.drop_table("user_settings")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("ix_login_requests_expires_at", table_name="login_requests")
    op.drop_index("ix_login_requests_ip_created_at", table_name="login_requests")
    op.drop_table("login_requests")
    op.drop_table("users")
