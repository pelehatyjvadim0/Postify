from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
import hmac
from inspect import isawaitable
import logging
import os
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4
from secrets import token_bytes

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.exc import NoResultFound
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from postify.web.dependencies import WebContainer, build_default_container
from postify.web.errors import ApiError, error_response
from postify.web.routes.api import router
from postify.web.security import (
    ACCESS_COOKIE,
    MUTATION_METHODS,
    access_token,
    same_origin,
    trusted_host,
    valid_capability,
)


LOGGER = logging.getLogger(__name__)


def create_app(
    container: WebContainer | None = None,
    *,
    trusted_hosts: tuple[str, ...] | None = None,
    access_password: str | None = None,
) -> FastAPI:
    selected_container = container or build_default_container()
    if trusted_hosts is None:
        configured_hosts = os.environ.get("POSTIFY_TRUSTED_HOSTS", "")
        trusted_hosts = tuple(
            host.strip() for host in configured_hosts.split(",") if host.strip()
        ) or ("127.0.0.1", "localhost", "::1", "testserver")
    if access_password is None:
        access_password = os.environ.get("POSTIFY_ACCESS_PASSWORD") or None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
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
    app.state.csrf_secret = token_bytes(32)
    app.state.trusted_hosts = frozenset(host.casefold() for host in trusted_hosts)
    app.state.access_password = access_password
    persistent_secret = os.environ.get("POSTIFY_SECRET_KEY", "").encode("utf-8")
    app.state.access_token = (
        access_token(persistent_secret or token_bytes(32), access_password)
        if access_password
        else None
    )

    @app.middleware("http")
    async def assign_request_id(request: Request, call_next):
        request.state.request_id = uuid4().hex
        if not trusted_host(request):
            return error_response(request, 400, "untrusted_host")
        if access_password and request.url.path != "/login":
            supplied = request.cookies.get(ACCESS_COOKIE, "")
            if not hmac.compare_digest(supplied, app.state.access_token):
                if request.url.path.startswith("/api/"):
                    return error_response(request, 401, "authentication_required")
                return RedirectResponse("/login", status_code=303)
        if request.url.path.startswith("/api/v1/") and request.method in MUTATION_METHODS:
            if not same_origin(request):
                return error_response(request, 403, "origin_rejected")
            if not valid_capability(request):
                return error_response(request, 403, "csrf_required")
        try:
            return await call_next(request)
        except Exception:
            return error_response(request, 503, "service_unavailable")

    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    async def login_page() -> HTMLResponse:
        return HTMLResponse(_login_page())

    @app.post("/login", response_class=HTMLResponse, include_in_schema=False)
    async def login(request: Request):
        body = await request.body()
        values = parse_qs(body[:4096].decode("utf-8", errors="replace"))
        supplied = values.get("password", [""])[0]
        if not access_password or not hmac.compare_digest(supplied, access_password):
            return HTMLResponse(_login_page(invalid=True), status_code=401)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            ACCESS_COOKIE,
            app.state.access_token,
            max_age=31_536_000,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
        )
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return error_response(
            request, error.status_code, error.code, details=error.details
        )

    @app.exception_handler(LookupError)
    async def not_found(request: Request, error: LookupError) -> JSONResponse:
        return error_response(request, 404, "not_found")

    @app.exception_handler(NoResultFound)
    async def missing_row(request: Request, error: NoResultFound) -> JSONResponse:
        return error_response(request, 404, "not_found")

    @app.exception_handler(StarletteHTTPException)
    async def missing_route(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        if error.status_code == 404:
            return error_response(request, 404, "not_found")
        return JSONResponse(
            status_code=error.status_code,
            content={"code": "http_error", "requestId": request.state.request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"code": "validation_error", "requestId": request.state.request_id},
        )

    @app.exception_handler(ValueError)
    async def invalid_domain_value(request: Request, error: ValueError) -> JSONResponse:
        from postify.domain.content.models import InvalidContentTransition

        if isinstance(error, InvalidContentTransition):
            return error_response(request, 409, "invalid_transition")
        return error_response(request, 422, "validation_error")

    @app.exception_handler(RuntimeError)
    async def runtime_conflict(request: Request, error: RuntimeError) -> JSONResponse:
        if str(error) == "operation_busy":
            return error_response(request, 409, "operation_busy")
        return error_response(request, 503, "service_unavailable")

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        return error_response(request, 503, "service_unavailable")

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


def _static_directory() -> Path:
    return Path(__file__).with_name("static")


def _login_page(*, invalid: bool = False) -> str:
    error = "<p>Неверный пароль</p>" if invalid else ""
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Вход · AutoPostTG</title><style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f4f6f8;font:16px system-ui;color:#17212b}}
form{{width:min(320px,calc(100% - 48px));padding:28px;background:#fff;border-radius:14px;box-shadow:0 8px 30px #17212b18}}
h1{{margin:0 0 20px;font-size:22px}}input,button{{box-sizing:border-box;width:100%;padding:12px;border-radius:8px;font:inherit}}
input{{border:1px solid #c8d0d8}}button{{margin-top:12px;border:0;background:#2481cc;color:#fff;cursor:pointer}}
p{{margin:12px 0 0;color:#c33;font-size:14px}}</style></head>
<body><form method="post" action="/login"><h1>AutoPostTG</h1>
<input type="password" name="password" placeholder="Пароль" autocomplete="current-password" autofocus required>
<button type="submit">Войти</button>{error}</form></body></html>"""
