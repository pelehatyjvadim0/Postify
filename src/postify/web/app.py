from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from postify.web.dependencies import WebContainer, build_default_container
from postify.web.errors import ApiError, NotFoundError, error_response
from postify.web.routes.api import router


def create_app(container: WebContainer | None = None) -> FastAPI:
    app = FastAPI()
    app.state.container = container or build_default_container()

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

    @app.get("/", include_in_schema=False)
    async def static_index() -> Response:
        index = Path(__file__).with_name("static") / "index.html"
        if not index.is_file():
            raise NotFoundError()
        return FileResponse(index)

    app.include_router(router)
    return app
