"""Примитивы безопасности веб-слоя.

Контур общего пароля снят: вход идёт через Telegram-бота, сессия лежит в
httpOnly cookie, а её токен в базе хранится хешем.

CSRF-токен выдаётся при входе и привязан к значению сессионной cookie: без
неё подделать заголовок нельзя, а хранить отдельную таблицу не нужно.
"""

from __future__ import annotations

from hashlib import sha256
import hmac
from secrets import token_urlsafe
from urllib.parse import urlsplit

from fastapi import Request

from postify.domain.auth.models import hash_session_token


SESSION_COOKIE = "postify_session"
CSRF_HEADER = "x-postify-csrf"
MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

__all__ = [
    "CSRF_HEADER",
    "MUTATION_METHODS",
    "SESSION_COOKIE",
    "csrf_token",
    "hash_session_token",
    "new_session_token",
    "same_origin",
    "trusted_host",
    "valid_csrf",
]


def new_session_token() -> str:
    """Токен сессии: 43 символа base64url, в базу уходит только его хеш."""
    return token_urlsafe(32)


def csrf_token(secret: bytes, session: str) -> str:
    """CSRF-токен, привязанный к конкретной сессии."""
    return hmac.new(secret, session.encode("utf-8"), sha256).hexdigest()


def valid_csrf(request: Request) -> bool:
    session = request.cookies.get(SESSION_COOKIE)
    supplied = request.headers.get(CSRF_HEADER)
    if not session or not supplied or len(session) > 256:
        return False
    expected = csrf_token(request.app.state.csrf_secret, session)
    return hmac.compare_digest(expected, supplied)


def same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin or origin == "null":
        return False
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return (
        parsed.scheme.casefold() == request.url.scheme.casefold()
        and parsed.netloc.casefold() == request.headers.get("host", "").casefold()
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
    )


def trusted_host(request: Request) -> bool:
    allowed = request.app.state.trusted_hosts
    return "*" in allowed or (request.url.hostname or "").casefold() in allowed
