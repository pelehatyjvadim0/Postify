"""HTTP-приложение: middleware безопасности, формат ошибок, отдача SPA.

Вход в приложение ставит трек аутентификации через ``install_auth``: здесь
остаются только общие для всех запросов проверки и перевод исключений в
единый формат ошибки из раздела 1 контракта API.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from inspect import isawaitable
import logging
import os
from pathlib import Path
from secrets import token_bytes
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import NoResultFound
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from postify.application.projects.manage_rubrics import RubricInUse
from postify.domain.posts.models import InvalidPostTransition, PublicationPlanExpired
from postify.web.auth import install_auth
from postify.web.dependencies import WebContainer, build_default_container
from postify.web.errors import ApiError, error_response
from postify.web.routes import API_ROUTERS
from postify.web.security import (
    MUTATION_METHODS,
    same_origin,
    trusted_host,
    valid_csrf,
)


LOGGER = logging.getLogger(__name__)

# Состояние объекта не допускает действия — 409 по контракту.
CONFLICT_RUNTIME = frozenset(
    {
        "operation_busy",
        "delivery_not_retryable",
        "channel_delivery_in_flight",
        "publication_channel_unavailable",
        "publication_secret_unavailable",
        "media_in_use",
    }
)

# Ошибки настройки сервера: пользователь их не исправит, это 500.
SERVER_RUNTIME = frozenset({"secret_storage_unavailable", "unsupported_operation"})

HTTP_ERROR_CODES = {
    401: "authentication_required",
    403: "origin_rejected",
    404: "not_found",
    405: "method_not_allowed",
    413: "media_too_large",
    429: "provider_rate_limited",
}


def create_app(
    container: WebContainer | None = None,
    *,
    trusted_hosts: tuple[str, ...] | None = None,
    auth: object | None = None,
) -> FastAPI:
    """Собирает приложение. ``auth`` подменяет сервис входа в тестах."""
    selected_container = container or build_default_container()
    if trusted_hosts is None:
        configured_hosts = os.environ.get("POSTIFY_TRUSTED_HOSTS", "")
        trusted_hosts = tuple(
            host.strip() for host in configured_hosts.split(",") if host.strip()
        ) or ("127.0.0.1", "localhost", "::1", "testserver")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        recover = getattr(selected_container.api, "recover_interrupted_operations", None)
        if callable(recover):
            await asyncio.to_thread(recover)
        scheduler_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="postify-scheduler"
        )
        scheduler_stop = asyncio.Event()
        task = asyncio.create_task(
            _poll_scheduler(
                selected_container.api, scheduler_executor, scheduler_stop
            ),
            name="postify-project-scheduler",
        )
        app.state.scheduler_task = task
        try:
            yield
        finally:
            scheduler_stop.set()
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await asyncio.shield(task)
                raise
            finally:
                await asyncio.to_thread(
                    scheduler_executor.shutdown,
                    wait=True,
                    cancel_futures=True,
                )
                close = getattr(selected_container.api, "close", None)
                if callable(close):
                    await asyncio.to_thread(close)

    app = FastAPI(lifespan=lifespan)
    app.state.container = selected_container
    app.state.trusted_hosts = frozenset(host.casefold() for host in trusted_hosts)
    # CSRF-токен привязан к сессии, а сессия живёт год. Если ключ задан, секрет
    # переживает перезапуск и вошедшим не приходится логиниться заново.
    persistent_secret = os.environ.get("POSTIFY_SECRET_KEY", "").encode("utf-8")
    app.state.csrf_secret = persistent_secret or token_bytes(32)
    # Ставится до собственного middleware: то, что добавлено позже, оборачивает
    # предыдущее, поэтому проверки ниже выполняются раньше проверки сессии и
    # ответ про вход тоже получает request_id.
    install_auth(app, auth=auth)

    @app.middleware("http")
    async def guard_request(request: Request, call_next):
        request.state.request_id = uuid4().hex
        if not trusted_host(request):
            return error_response(request, 400, "untrusted_host")
        if request.url.path.startswith("/api/") and request.method in MUTATION_METHODS:
            if not same_origin(request):
                return error_response(request, 400, "origin_rejected")
            # Вход идёт без сессии, поэтому CSRF-токена у него ещё нет:
            # эти маршруты защищены только совпадением Origin.
            if not request.url.path.startswith("/api/auth/") and not valid_csrf(
                request
            ):
                return error_response(request, 400, "csrf_required")
        try:
            return await call_next(request)
        except Exception:
            LOGGER.exception("Необработанная ошибка запроса")
            return error_response(request, 500, "internal_error")

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return error_response(
            request, error.status_code, error.code, error.message, field=error.field
        )

    @app.exception_handler(LookupError)
    async def not_found(request: Request, error: LookupError) -> JSONResponse:
        return error_response(request, 404, "not_found")

    @app.exception_handler(NoResultFound)
    async def missing_row(request: Request, error: NoResultFound) -> JSONResponse:
        return error_response(request, 404, "not_found")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        code = HTTP_ERROR_CODES.get(error.status_code, "http_error")
        return error_response(request, error.status_code, code)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            request, 422, "validation_error", field=_first_field(error)
        )

    @app.exception_handler(ResponseValidationError)
    async def invalid_response(
        request: Request, error: ResponseValidationError
    ) -> JSONResponse:
        # Ответ разошёлся с контрактом: это дефект сервера, а не запроса.
        LOGGER.error("Ответ не прошёл схему контракта", exc_info=error)
        return error_response(request, 500, "internal_error")

    @app.exception_handler(RubricInUse)
    async def rubric_in_use(request: Request, error: RubricInUse) -> JSONResponse:
        return error_response(request, 409, "rubric_in_use")

    @app.exception_handler(ValueError)
    async def invalid_domain_value(request: Request, error: ValueError) -> JSONResponse:
        if isinstance(error, PublicationPlanExpired):
            return error_response(request, 409, "publication_plan_expired", str(error))
        if isinstance(error, InvalidPostTransition):
            return error_response(request, 409, "invalid_transition", str(error))
        # Домен пишет сообщения по-русски и для человека: их можно показывать.
        return error_response(request, 422, "validation_error", str(error))

    @app.exception_handler(RuntimeError)
    async def runtime_conflict(request: Request, error: RuntimeError) -> JSONResponse:
        code = str(error)
        if code in CONFLICT_RUNTIME:
            return error_response(request, 409, code)
        if code in SERVER_RUNTIME:
            return error_response(request, 500, code)
        LOGGER.error("Неожиданная ошибка выполнения", exc_info=error)
        return error_response(request, 500, "internal_error")

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        LOGGER.error("Необработанное исключение", exc_info=error)
        return error_response(request, 500, "internal_error")

    for router in API_ROUTERS:
        app.include_router(router)
    static = _static_directory()
    if static.is_dir():
        app.mount("/static", StaticFiles(directory=static), name="static-assets")
        app.mount("/", StaticFiles(directory=static, html=True), name="static")
    return app


async def _poll_scheduler(
    api, executor: ThreadPoolExecutor, stop: asyncio.Event
) -> None:
    loop = asyncio.get_running_loop()
    while not stop.is_set():
        try:
            result = await loop.run_in_executor(executor, api.scheduler_tick)
            if isawaitable(result):
                await result
        except Exception:
            LOGGER.exception("Project scheduler tick failed")
        if stop.is_set():
            return
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=0.1)


def _first_field(error: RequestValidationError) -> str | None:
    """Имя первого непрошедшего поля: контракт кладёт его рядом с кодом."""
    for item in error.errors():
        location = item.get("loc") or ()
        if location:
            return str(location[-1])
    return None


def _static_directory() -> Path:
    return Path(__file__).with_name("static")
