from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from inspect import isawaitable
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import NoResultFound
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from postify.web.dependencies import WebContainer, build_default_container
from postify.web.errors import ApiError, error_response
from postify.web.routes.api import router


LOGGER = logging.getLogger(__name__)


def create_app(container: WebContainer | None = None) -> FastAPI:
    selected_container = container or build_default_container()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(
            _poll_scheduler(selected_container.api), name="postify-project-scheduler"
        )
        app.state.scheduler_task = task
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(lifespan=lifespan)
    app.state.container = selected_container

    @app.middleware("http")
    async def assign_request_id(request: Request, call_next):
        request.state.request_id = uuid4().hex
        try:
            return await call_next(request)
        except Exception:
            return error_response(request, 503, "service_unavailable")

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return error_response(request, error.status_code, error.code)

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
        app.mount("/", StaticFiles(directory=static, html=True), name="static")
    return app


async def _poll_scheduler(api) -> None:
    while True:
        try:
            result = api.scheduler_tick()
            if isawaitable(result):
                await result
        except Exception:
            LOGGER.exception("Project scheduler tick failed")
        await asyncio.sleep(0.1)


def _static_directory() -> Path:
    return Path(__file__).with_name("static")
