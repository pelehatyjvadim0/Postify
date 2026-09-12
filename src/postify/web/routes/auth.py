"""Эндпоинты входа: /api/auth/* и /api/me.

Поведение повторяет образец FakeTG: POST /login выдаёт пару токенов и ссылку
на бота, браузер опрашивает статус раз в полторы секунды, а на ``approved``
этот же ответ ставит сессионную cookie и гасит запрос.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from postify.domain.auth.models import (
    APPROVED,
    LOGIN_RETRY_AFTER_SECONDS,
    SESSION_TTL,
    LoginNotAllowed,
    LoginRequestExpired,
    TelegramUnavailable,
    TooManyLoginAttempts,
    User,
)
from postify.web.errors import error_response
from postify.web.security import SESSION_COOKIE, csrf_token, same_origin, valid_csrf


router = APIRouter(prefix="/api", tags=["auth"])

# Тексты ошибок входа; общий словарь errors.py их не знает, поэтому сообщение
# передаётся явно — формат ответа остаётся единым.
MESSAGES = {
    "origin_rejected": "Источник запроса не совпадает с адресом приложения",
    "csrf_required": "Не хватает защитного заголовка запроса",
    "authentication_required": "Нужно войти в приложение",
    "login_not_allowed": "Вход для этого Telegram-аккаунта не разрешён",
    "telegram_unavailable": "Вход через Telegram временно недоступен",
    "too_many_login_attempts": "Слишком много попыток. Повторите через 5 минут.",
}


def auth_error(request: Request, status_code: int, code: str) -> JSONResponse:
    return error_response(request, status_code, code, MESSAGES.get(code))


def user_payload(service, user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "telegram_user_id": user.telegram_user_id,
        "telegram_username": user.telegram_username,
        "display_name": user.display_name,
        "created_at": _iso(user.created_at),
        "common_prompt": service.repository.common_prompt(user.id),
    }


@router.post("/auth/login", status_code=201)
def start_login(request: Request):
    """Выдаёт browser_token и ссылку на бота. Сессии не требует, Origin — да."""
    service = request.app.state.auth
    if not same_origin(request):
        return auth_error(request, 400, "origin_rejected")
    try:
        login_request, telegram_url = service.start_login(ip=_client_ip(request))
    except TooManyLoginAttempts:
        limited = auth_error(request, 429, "too_many_login_attempts")
        limited.headers["Retry-After"] = str(LOGIN_RETRY_AFTER_SECONDS)
        return limited
    except TelegramUnavailable:
        return auth_error(request, 503, "telegram_unavailable")
    # telegram_token остаётся между сервером и ботом и наружу не уходит.
    return JSONResponse(
        status_code=201,
        content={
            "browser_token": login_request.browser_token,
            "telegram_url": telegram_url,
            "expires_at": _iso(login_request.expires_at),
        },
    )


@router.get("/auth/login/status")
def login_status(request: Request):
    """Поллинг статуса. На approved ставит cookie этим же ответом."""
    service = request.app.state.auth
    browser_token = request.query_params.get("request", "")
    try:
        status = service.complete_login.status(browser_token)
    except LoginRequestExpired:
        # Неизвестный и истёкший запрос неотличимы, тело по контракту особое.
        return JSONResponse(status_code=404, content={"status": "expired"})
    if status != APPROVED:
        return JSONResponse(status_code=200, content={"status": status})
    try:
        session = service.complete_login(browser_token)
    except LoginNotAllowed:
        return auth_error(request, 403, "login_not_allowed")
    except LoginRequestExpired:
        return JSONResponse(status_code=404, content={"status": "expired"})
    result = JSONResponse(
        status_code=200,
        content={
            "status": APPROVED,
            "user": user_payload(service, session.user),
            "csrf": csrf_token(request.app.state.csrf_secret, session.token),
        },
    )
    result.set_cookie(
        SESSION_COOKIE,
        session.token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )
    return result


@router.post("/auth/logout", status_code=204)
def logout(request: Request):
    """Общая проверка мутаций пропускает /api/auth/* без CSRF, поэтому
    выход проверяет заголовок сам: сессия у него уже есть."""
    service = request.app.state.auth
    if not same_origin(request):
        return auth_error(request, 400, "origin_rejected")
    if not valid_csrf(request):
        return auth_error(request, 400, "csrf_required")
    service.logout(request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me")
def me(request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        return auth_error(request, 401, "authentication_required")
    return JSONResponse(
        status_code=200, content=user_payload(request.app.state.auth, user),
        headers={
            "x-postify-csrf": csrf_token(request.app.state.csrf_secret, request.cookies[SESSION_COOKIE]),
            "Cache-Control": "no-store",
        },
    )


def _iso(value: datetime) -> str:
    return value.isoformat()


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
