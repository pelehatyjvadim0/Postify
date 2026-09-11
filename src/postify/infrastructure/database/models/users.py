"""ORM-модели входа и владения данными.

Запросы на вход и сессии лежат в таблицах, а не в памяти процесса: иначе
перезапуск контейнера разлогинивает всех. Токен сессии в базе хранится только
хешем — утечка дампа не даёт войти.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from postify.infrastructure.database.models.base import Base


class UserModel(Base):
    """Пользователь. Личность — telegram_user_id, паролей и почты нет."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Строка, а не число: id Telegram шире int32 и сравнивается как строка.
    telegram_user_id: Mapped[str] = mapped_column(
        String, nullable=False, unique=True
    )
    telegram_username: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)


class LoginRequestModel(Base):
    """Запрос на вход: пара токенов, состояние подтверждения и TTL."""

    __tablename__ = "login_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','confirmation','approved','denied')",
            name="ck_login_requests_status",
        ),
        # Лимит попыток с одного IP и уборка истёкших читают эти колонки.
        Index("ix_login_requests_ip_created_at", "ip", "created_at"),
        Index("ix_login_requests_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Уходит только в диплинк бота, фронтенду не отдаётся.
    telegram_token: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # Остаётся у браузера, по нему идёт поллинг статуса.
    browser_token: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    # Заполняется в момент /start: подтвердить может только этот же аккаунт.
    telegram_user_id: Mapped[str | None] = mapped_column(String)
    telegram_username: Mapped[str | None] = mapped_column(String)
    display_name: Mapped[str | None] = mapped_column(String)
    ip: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSessionModel(Base):
    """Сессия браузера. В базе только хеш токена, сам токен живёт в cookie."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserSettingsModel(Base):
    """Общий промпт пользователя, один на все его проекты."""

    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    common_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
