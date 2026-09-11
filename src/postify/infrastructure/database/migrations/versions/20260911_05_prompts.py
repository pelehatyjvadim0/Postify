"""Промпты: системный промпт сервера и промпт проекта.

Контекст генерации собирается из трёх уровней промптов. Общий промпт
пользователя уже лежит в ``user_settings`` (ревизия 02), здесь появляются
остальные два.

``app_settings`` — таблица ровно на одну строку: системный промпт один на весь
сервер. Единственность держит база (``CHECK (id = 1)``), а не код: второй
строки не появится даже при правке промпта напрямую в базе, а значит читателю
не придётся выбирать между двумя настройками. Строка вставляется здесь же,
чтобы чтение промпта не зависело от того, правил ли его кто-нибудь.

``content_projects.topic`` переименована в ``project_prompt``: темы переехали
в слоты контент-плана, а это поле с самого начала заполняется описанием
проекта и стало его промптом (решение T0, раздел 14 трейса). Отдельной колонки
не заводим.

Revision ID: 20260911_05
Revises: 20260911_02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260911_05"
down_revision = "20260911_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        # Ключ-константа: единственная строка настроек сервера.
        sa.Column("id", sa.SmallInteger(), primary_key=True, server_default="1"),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_app_settings_single_row"),
    )
    op.execute(
        "INSERT INTO app_settings (id, system_prompt, updated_at)"
        " VALUES (1, '', now())"
    )

    op.alter_column("content_projects", "topic", new_column_name="project_prompt")


def downgrade() -> None:
    op.alter_column("content_projects", "project_prompt", new_column_name="topic")
    op.drop_table("app_settings")
