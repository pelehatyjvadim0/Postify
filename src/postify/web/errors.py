from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self, status_code: int, code: str, details: dict[str, object] | None = None
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.details = _safe_details(code, details)


class NotFoundError(ApiError):
    def __init__(self) -> None:
        super().__init__(404, "not_found")


class ConflictError(ApiError):
    def __init__(
        self, code: str = "conflict", details: dict[str, object] | None = None
    ) -> None:
        super().__init__(409, code, details)


def _safe_details(
    code: str, details: dict[str, object] | None
) -> dict[str, object]:
    if code != "review_unresolved" or details is None:
        return {}
    values = details.get("unresolvedPackageIds")
    if not isinstance(values, (tuple, list)):
        return {}
    identifiers = [value for value in values if type(value) is int and value > 0]
    return {"unresolvedPackageIds": identifiers[:50]}


def request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else uuid4().hex


def error_response(
    request: Request,
    status_code: int,
    code: str,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "requestId": request_id(request), **(details or {})},
    )
