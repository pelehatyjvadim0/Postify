"""Фасад аутентификации для веб-слоя.

Даёт три вещи: ``install_auth`` подключает роутер, проверку сессии и цикл
опроса бота; ``current_user`` отдаёт вошедшего; ``owned_project`` проверяет
владение проектом.

``owned_project`` — единственная точка проверки владения. Ручных проверок в
обработчиках быть не должно: их около сорока, и пропуск одной выдаёт чужие
данные (риск Р7).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import os
from secrets import token_bytes

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from postify.application.auth.service import AuthService
from postify.domain.auth.models import User
from postify.web.errors import error_response
from postify.web.security import SESSION_COOKIE


LOGGER = logging.getLogger(__name__)

# Эти пути работают без сессии: сам вход и поллинг его статуса.
PUBLIC_PREFIX = "/api/auth/"


class AuthHttpError(HTTPException):
    """Ошибка зависимостей входа; рендерится в формат ошибки контракта."""


def install_auth(app: FastAPI, *, auth: AuthService | None = None, poller=None) -> None:
    """Подключает вход: роутер, проверку сессии и цикл опроса бота.

    ``auth`` и ``poller`` передают тесты и сборка; по умолчанию сервис
    строится из настроек, а цикл опроса — из токена бота.
    """
    # Импорт роутера отложен: его соседи по пакету сами зависят от этого
    # модуля, и на верхнем уровне получился бы цикл.
    from postify.web.routes.auth import router

    service = auth if auth is not None else _service_from_settings()
    app.state.auth = service
    if getattr(app.state, "csrf_secret", None) is None:
        # Секрет из окружения переживает перезапуск: иначе после рестарта
        # CSRF-токены вошедших разом становятся недействительными.
        persistent = os.environ.get("POSTIFY_SECRET_KEY", "").encode("utf-8")
        app.state.csrf_secret = persistent or token_bytes(32)
    app.include_router(router)
    app.add_exception_handler(AuthHttpError, _render_auth_error)

    @app.middleware("http")
    async def require_session(request: Request, call_next):
        """Без действующей сессии любой /api/* кроме /api/auth/* отвечает 401."""
        token = request.cookies.get(SESSION_COOKIE)
        request.state.user = (
            await run_in_threadpool(service.resolve_session, token) if token else None
        )
        path = request.url.path
        if (
            path.startswith("/api/")
            and not path.startswith(PUBLIC_PREFIX)
            and request.state.user is None
        ):
            return _render_auth_error(
                request, AuthHttpError(401, "authentication_required")
            )
        return await call_next(request)

    _install_polling(app, service, poller)


def _render_auth_error(request: Request, error: AuthHttpError):
    from postify.web.routes.auth import MESSAGES

    code = str(error.detail)
    return error_response(request, error.status_code, code, MESSAGES.get(code))


def current_user(request: Request) -> User:
    """Текущий пользователь. Сессию уже разобрала общая проверка."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise AuthHttpError(status_code=401, detail="authentication_required")
    return user


def owned_project(
    project_id: int, request: Request, user: User = Depends(current_user)
) -> int:
    """Проверяет владение проектом из пути и возвращает его идентификатор.

    Чужой и несуществующий проект отвечают одинаково — 404: существование
    чужих проектов не раскрывается.
    """
    service = request.app.state.auth
    if not service.owns_project(user_id=user.id, project_id=project_id):
        raise AuthHttpError(status_code=404, detail="not_found")
    return project_id


def _install_polling(app: FastAPI, service: AuthService, poller) -> None:
    """Оборачивает жизненный цикл приложения запуском цикла опроса бота."""
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(instance: FastAPI):
        async with _polling(service, poller):
            async with previous(instance) as state:
                yield state

    app.router.lifespan_context = lifespan


@asynccontextmanager
async def _polling(service: AuthService, poller):
    """Один цикл getUpdates на процесс; на остановке задача снимается."""
    client = None
    if poller is None:
        token = _auth_bot_token()
        if token is None:
            # Без токена вход невозможен: POST /api/auth/login ответит 503.
            LOGGER.error("POSTIFY_AUTH_BOT_TOKEN не задан: вход через бота отключён")
            yield
            return
        from postify.adapters.telegram.auth_bot import AuthBotPoller, TelegramAuthBot
        from postify.config import Settings

        client = httpx.AsyncClient()
        poller = AuthBotPoller(
            TelegramAuthBot(client, bot_token=token, relay_url=Settings().auth_bot_relay_url),
            service,
        )

    task = asyncio.create_task(poller.run(), name="postify-auth-bot")
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        if client is not None:
            await client.aclose()


def _auth_bot_token() -> str | None:
    from postify.config import Settings

    with suppress(Exception):
        token = Settings().auth_bot_token
        if token is not None:
            return token.get_secret_value()
    return None


def _service_from_settings() -> AuthService:
    from sqlalchemy.orm import sessionmaker

    from postify.config import Settings
    from postify.infrastructure.database.engine import create_engine_from_settings
    from postify.infrastructure.repositories.sqlalchemy_users import (
        SqlAlchemyUserRepository,
    )

    settings = Settings()
    engine = create_engine_from_settings(settings)
    return AuthService(
        SqlAlchemyUserRepository(sessionmaker(engine, expire_on_commit=False)),
        allowlist=settings.allowed_telegram_ids,
        bot_username=settings.auth_bot_username,
    )
