"""Хранилище двух уровней промптов: сервера и пользователя.

Третий уровень — промпт проекта — лежит в ``content_projects.project_prompt``
и читается через репозиторий проектов, отдельного хранилища ему не нужно.

Всё синхронное, как остальные репозитории проекта.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from postify.infrastructure.database.models.prompts import (
    APP_SETTINGS_ID,
    AppSettingsModel,
)
from postify.infrastructure.database.models.users import UserSettingsModel


class SqlAlchemyPromptRepository:
    """Чтение и запись системного промпта сервера и общего промпта пользователя."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    # --- системный промпт сервера ----------------------------------------

    def system_prompt(self) -> str:
        """Промпт сервера. Пустая строка — промпт ещё не задавали."""
        with self._session_factory() as session:
            model = session.get(AppSettingsModel, APP_SETTINGS_ID)
            return model.system_prompt if model is not None else ""

    def set_system_prompt(self, prompt: str, *, now: datetime) -> str:
        """Заменяет промпт сервера целиком; частичной правки у него нет.

        Строку заводит миграция, но она может быть стёрта при ручной правке
        базы — поэтому запись умеет создать её заново.
        """
        with self._session_factory() as session:
            try:
                model = session.get(
                    AppSettingsModel, APP_SETTINGS_ID, with_for_update=True
                )
                if model is None:
                    model = AppSettingsModel(id=APP_SETTINGS_ID)
                    session.add(model)
                model.system_prompt = prompt
                model.updated_at = now
                session.commit()
                return prompt
            except BaseException:
                session.rollback()
                raise

    # --- общий промпт пользователя ---------------------------------------

    def common_prompt(self, user_id: int) -> str:
        """Общий промпт пользователя; до первой правки строки просто нет."""
        with self._session_factory() as session:
            value = session.scalar(
                select(UserSettingsModel.common_prompt).where(
                    UserSettingsModel.user_id == user_id
                )
            )
            return value or ""

    def set_common_prompt(self, user_id: int, prompt: str, *, now: datetime) -> str:
        """Сохраняет общий промпт, заводя строку настроек при первой записи."""
        with self._session_factory() as session:
            try:
                model = session.get(
                    UserSettingsModel, user_id, with_for_update=True
                )
                if model is None:
                    model = UserSettingsModel(user_id=user_id)
                    session.add(model)
                model.common_prompt = prompt
                model.updated_at = now
                session.commit()
                return prompt
            except BaseException:
                session.rollback()
                raise
