"""Добавить явный профиль модели анализа Codex.

Revision ID: 20260817_10
Revises: 20260817_09
"""

from alembic import op


revision = "20260817_10"
down_revision = "20260817_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE content_projects
        SET configuration = configuration ||
            '{"analysis_model":"gpt-5.6-luna","analysis_reasoning_effort":"high"}'::jsonb
        WHERE configuration ? 'analysis_timeout_seconds'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE content_projects
        SET configuration = configuration
            - 'analysis_model'
            - 'analysis_reasoning_effort'
        """
    )
