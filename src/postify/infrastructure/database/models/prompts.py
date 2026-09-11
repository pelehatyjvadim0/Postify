"""ORM-модель настроек сервера.

Системный промпт — уровень разработчика, а не пользователя: в API его нет
(раздел 13 контракта), правится он через CLI или прямо в базе. Поэтому он
живёт в отдельной таблице на одну строку, а не в настройках пользователя.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from postify.infrastructure.database.models.base import Base


# Идентификатор единственной строки: таблица настроек сервера — синглтон.
APP_SETTINGS_ID = 1


class AppSettingsModel(Base):
    """Настройки сервера. Строка ровно одна, её гарантирует CHECK."""

    __tablename__ = "app_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_app_settings_single_row"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default="1")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
