"""Доменные модели и инварианты входа через Telegram-бота.

Личность пользователя — ``telegram_user_id``. Паролей, почты и отдельной
регистрации нет: аккаунт заводится при первом подтверждённом входе.

Здесь же лежат ошибки домена: web-слой переводит их в коды контракта, а цикл
опроса бота — в текст сообщения пользователю.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256


# TTL зафиксированы контрактом: запрос на вход живёт 10 минут, сессия — год.
LOGIN_REQUEST_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(days=365)

# Окно и порог лимита неудачных попыток с одного IP.
LOGIN_FAILURE_WINDOW = timedelta(minutes=5)
LOGIN_FAILURE_LIMIT = 10
LOGIN_RETRY_AFTER_SECONDS = 300

# Потолок одновременных незакрытых запросов на вход: защита от забивания
# таблицы, значение перенесено из образца FakeTG.
MAX_ACTIVE_LOGIN_REQUESTS = 5000

PENDING = "pending"
CONFIRMATION = "confirmation"
APPROVED = "approved"
DENIED = "denied"
LOGIN_STATUSES = frozenset({PENDING, CONFIRMATION, APPROVED, DENIED})


class AuthError(Exception):
    """Базовая ошибка входа; ``code`` совпадает с кодом контракта API."""

    code = "authentication_failed"


class LoginRequestExpired(AuthError):
    """Запрос на вход неизвестен, истёк или уже погашен."""

    code = "login_request_expired"


class LoginDenied(AuthError):
    """Пользователь нажал «Это не я»."""

    code = "login_denied"


class LoginNotAllowed(AuthError):
    """Вход по списку разрешённых включён, этого telegram_user_id в нём нет."""

    code = "login_not_allowed"


class TelegramUnavailable(AuthError):
    """Бот входа недоступен: имя бота не известно, ссылку выдать нечем."""

    code = "telegram_unavailable"


class TooManyLoginAttempts(AuthError):
    """Превышен лимит попыток входа с одного IP."""

    code = "too_many_login_attempts"


@dataclass(frozen=True, slots=True)
class User:
    id: int
    telegram_user_id: str
    telegram_username: str
    display_name: str
    created_at: datetime
    last_login_at: datetime | None
    is_active: bool


@dataclass(frozen=True, slots=True)
class LoginRequest:
    """Запрос на вход: пара токенов и состояние подтверждения."""

    id: int
    telegram_token: str
    browser_token: str
    status: str
    telegram_user_id: str | None
    telegram_username: str | None
    display_name: str | None
    ip: str | None
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None

    def is_live(self, now: datetime) -> bool:
        """Запрос ещё можно использовать: срок не вышел."""
        return self.expires_at > now


@dataclass(frozen=True, slots=True)
class TelegramIdentity:
    """Кто именно нажал кнопку в боте."""

    telegram_user_id: str
    telegram_username: str
    display_name: str


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """Выданная сессия: сырой токен уходит в cookie, в базе лежит его хеш."""

    user: User
    token: str
    expires_at: datetime


def allowed(telegram_user_id: str, allowlist: frozenset[str]) -> bool:
    """Пустой список означает открытый вход (риск Р9 закрывается настройкой)."""
    return not allowlist or telegram_user_id in allowlist


def display_name_of(first_name: str, last_name: str, username: str) -> str:
    """Имя для интерфейса: ФИО из профиля, иначе @username, иначе пусто."""
    full = " ".join(part for part in (first_name, last_name) if part).strip()
    return full or username


def hash_session_token(token: str) -> str:
    """Хеш токена сессии: в базе лежит он, сам токен живёт только в cookie."""
    return sha256(token.encode("utf-8")).hexdigest()
