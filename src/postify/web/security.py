from __future__ import annotations

from hashlib import sha256
import hmac
from secrets import token_urlsafe
from urllib.parse import urlsplit

from fastapi import Request


SESSION_COOKIE = "postify_session"
ACCESS_COOKIE = "postify_access"
CSRF_HEADER = "x-postify-csrf"
MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def new_session() -> str:
    return token_urlsafe(32)


def capability(secret: bytes, session: str) -> str:
    return hmac.new(secret, session.encode("utf-8"), sha256).hexdigest()


def access_token(secret: bytes, password: str) -> str:
    return hmac.new(secret, password.encode("utf-8"), sha256).hexdigest()


def valid_capability(request: Request) -> bool:
    session = request.cookies.get(SESSION_COOKIE)
    supplied = request.headers.get(CSRF_HEADER)
    if not session or not supplied or len(session) > 256:
        return False
    expected = capability(request.app.state.csrf_secret, session)
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
