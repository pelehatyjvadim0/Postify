"""Действия входа. Здесь держатся все доменные инварианты входа.

Механика повторяет образец FakeTG: пара токенов, подтверждение в боте от того
же telegram_user_id, поллинг статуса браузером и выдача сессии на ``approved``.
Отличие одно — состояние живёт в PostgreSQL, а не в памяти процесса.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from secrets import token_urlsafe

from postify.domain.auth.models import (
    APPROVED,
    DENIED,
    LOGIN_FAILURE_LIMIT,
    LOGIN_FAILURE_WINDOW,
    LOGIN_REQUEST_TTL,
    MAX_ACTIVE_LOGIN_REQUESTS,
    SESSION_TTL,
    IssuedSession,
    LoginDenied,
    LoginNotAllowed,
    LoginRequest,
    LoginRequestExpired,
    TelegramIdentity,
    TooManyLoginAttempts,
    User,
    allowed,
    hash_session_token,
)


Clock = Callable[[], datetime]


class StartLogin:
    """Выпускает пару токенов и ссылку на бота.

    ``username`` отдаёт цикл опроса: имя берётся из настройки, а при её
    отсутствии — из ``getMe``. Пока имя не известно, вход невозможен и
    действие поднимает ``TelegramUnavailable`` через провайдера.
    """

    def __init__(
        self,
        repository,
        *,
        username: Callable[[], str],
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._username = username
        self._clock = clock

    def __call__(self, *, ip: str | None) -> tuple[LoginRequest, str]:
        bot_username = self._username()
        now = self._clock()
        # Уборка до проверок: истёкшие запросы не должны занимать лимит.
        self._repository.purge_expired(now)
        if (
            self._repository.failed_attempts(ip=ip, since=now - LOGIN_FAILURE_WINDOW)
            >= LOGIN_FAILURE_LIMIT
            or self._repository.active_login_requests(now) >= MAX_ACTIVE_LOGIN_REQUESTS
        ):
            raise TooManyLoginAttempts()
        request = self._repository.create_login_request(
            # 43 символа base64url, как в диплинке образца.
            telegram_token=token_urlsafe(32),
            browser_token=token_urlsafe(32),
            ip=ip,
            now=now,
            expires_at=now + LOGIN_REQUEST_TTL,
        )
        url = f"https://t.me/{bot_username}?start=autopost_login_{request.telegram_token}"
        return request, url


class HandleBotStart:
    """Бот получил ``/start autopost_login_<token>``: запрос переходит в confirmation."""

    def __init__(self, repository, *, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    def __call__(
        self, *, telegram_token: str, identity: TelegramIdentity
    ) -> LoginRequest:
        request = self._repository.mark_confirmation(
            telegram_token=telegram_token,
            telegram_user_id=identity.telegram_user_id,
            telegram_username=identity.telegram_username,
            display_name=identity.display_name,
            now=self._clock(),
        )
        if request is None:
            raise LoginRequestExpired()
        return request


class HandleBotDecision:
    """Нажата кнопка «Это я» или «Это не я».

    Подтвердить может только тот telegram_user_id, который прислал ``/start``:
    иначе чужой, перехвативший ссылку, входил бы под владельцем бота.
    """

    def __init__(self, repository, *, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    def __call__(
        self, *, telegram_token: str, telegram_user_id: str, approved: bool
    ) -> LoginRequest:
        request = self._repository.decide(
            telegram_token=telegram_token,
            status=APPROVED if approved else DENIED,
            telegram_user_id=telegram_user_id,
            now=self._clock(),
        )
        if request is None:
            raise LoginRequestExpired()
        return request


class CompleteLogin:
    """Отдаёт статус запроса, а на ``approved`` выдаёт сессию.

    Аккаунт заводится здесь же: первый подтверждённый вход и есть регистрация.
    Список разрешённых проверяется в этой единственной точке — подтверждение
    личности в боте и допуск ко входу это разные вещи.
    """

    def __init__(
        self,
        repository,
        *,
        allowlist: frozenset[str],
        clock: Clock,
        session_token: Callable[[], str] = lambda: token_urlsafe(32),
        hash_token: Callable[[str], str] = hash_session_token,
    ) -> None:
        self._repository = repository
        self._allowlist = allowlist
        self._clock = clock
        self._session_token = session_token
        self._hash_token = hash_token

    def status(self, browser_token: str) -> str:
        """Состояние запроса для поллинга; истёкший неотличим от неизвестного."""
        request = self._repository.login_request_by_browser_token(browser_token)
        if request is None or not request.is_live(self._clock()):
            raise LoginRequestExpired()
        return request.status

    def __call__(self, browser_token: str) -> IssuedSession:
        request = self._repository.login_request_by_browser_token(browser_token)
        now = self._clock()
        if request is None or not request.is_live(now):
            raise LoginRequestExpired()
        if request.status == DENIED:
            raise LoginDenied()
        if request.status != APPROVED or request.telegram_user_id is None:
            raise LoginRequestExpired()
        if not allowed(request.telegram_user_id, self._allowlist):
            raise LoginNotAllowed()
        user = self._repository.ensure_user(
            telegram_user_id=request.telegram_user_id,
            telegram_username=request.telegram_username or "",
            display_name=request.display_name or "",
            now=now,
        )
        token = self._session_token()
        expires_at = now + SESSION_TTL
        self._repository.create_session(
            user_id=user.id,
            token_hash=self._hash_token(token),
            now=now,
            expires_at=expires_at,
        )
        # Запрос гасится: повторный поллинг увидит «истёк» и второй cookie
        # по той же ссылке не выдаётся.
        self._repository.consume_login_request(request.id)
        return IssuedSession(user=user, token=token, expires_at=expires_at)


class ResolveSession:
    """Пользователь по токену из cookie. В базе лежит только хеш токена."""

    def __init__(
        self,
        repository,
        *,
        clock: Clock,
        hash_token: Callable[[str], str] = hash_session_token,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._hash_token = hash_token

    def __call__(self, token: str | None) -> User | None:
        if not token or len(token) > 256:
            return None
        return self._repository.session_user(
            token_hash=self._hash_token(token), now=self._clock()
        )


class Logout:
    """Удаляет сессию. Неизвестный токен — не ошибка, выход идемпотентен."""

    def __init__(
        self, repository, *, hash_token: Callable[[str], str] = hash_session_token
    ) -> None:
        self._repository = repository
        self._hash_token = hash_token

    def __call__(self, token: str | None) -> None:
        if not token or len(token) > 256:
            return
        self._repository.delete_session(self._hash_token(token))
