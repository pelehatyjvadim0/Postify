from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code


class NotFoundError(ApiError):
    def __init__(self) -> None:
        super().__init__(404, "not_found")


class ConflictError(ApiError):
    def __init__(self, code: str = "conflict") -> None:
        super().__init__(409, code)


def request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else uuid4().hex


def error_response(request: Request, status_code: int, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "requestId": request_id(request)},
    )
