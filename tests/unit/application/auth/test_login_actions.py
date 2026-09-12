"""Действия входа: полный сценарий и все отказы.

Набор случаев повторяет проверочный сценарий FakeTG
(``~/Desktop/FakeTG/web/check-telegram-auth.mjs``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from postify.application.auth.service import AuthService
from postify.domain.auth.models import (
    LOGIN_FAILURE_LIMIT,
    LOGIN_REQUEST_TTL,
    SESSION_TTL,
    LoginDenied,
    LoginNotAllowed,
    LoginRequestExpired,
    TelegramIdentity,
    TelegramUnavailable,
    TooManyLoginAttempts,
    hash_session_token,
)

from .fakes import FakeUserRepository


NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
OWNER = TelegramIdentity(
    telegram_user_id="101", telegram_username="user_101", display_name="Иван Петров"
)
STRANGER = TelegramIdentity(
    telegram_user_id="202", telegram_username="user_202", display_name="Чужой"
)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


def build(allowlist: frozenset[str] = frozenset(), bot_username: str = "autopost_bot"):
    repository = FakeUserRepository()
    clock = Clock()
    service = AuthService(
        repository, allowlist=allowlist, bot_username=bot_username, clock=clock
    )
    return repository, service, clock


def full_login(service, identity: TelegramIdentity = OWNER):
    request, url = service.start_login(ip="10.0.0.1")
    service.handle_bot_start(
        telegram_token=request.telegram_token, identity=identity
    )
    service.handle_bot_decision(
        telegram_token=request.telegram_token,
        telegram_user_id=identity.telegram_user_id,
        approved=True,
    )
    return request, url


def test_successful_login_walks_every_status_and_creates_the_user() -> None:
    repository, service, _ = build()

    request, url = service.start_login(ip="10.0.0.1")
    assert len(request.telegram_token) == 43
    assert request.browser_token != request.telegram_token
    assert url == f"https://t.me/autopost_bot?start=autopost_login_{request.telegram_token}"
    assert request.expires_at == NOW + LOGIN_REQUEST_TTL
    assert service.complete_login.status(request.browser_token) == "pending"

    service.handle_bot_start(telegram_token=request.telegram_token, identity=OWNER)
    assert service.complete_login.status(request.browser_token) == "confirmation"

    service.handle_bot_decision(
        telegram_token=request.telegram_token,
        telegram_user_id=OWNER.telegram_user_id,
        approved=True,
    )
    assert service.complete_login.status(request.browser_token) == "approved"

    session = service.complete_login(request.browser_token)
    assert session.user.telegram_user_id == "101"
    assert session.user.display_name == "Иван Петров"
    assert session.expires_at == NOW + SESSION_TTL
    # Запрос погашен: по той же ссылке второй cookie не выдаётся.
    with pytest.raises(LoginRequestExpired):
        service.complete_login.status(request.browser_token)
    assert service.resolve_session(session.token) == session.user


def test_session_token_is_stored_only_as_a_hash() -> None:
    # Поломка: открытый токен в базе делает дамп эквивалентом входа.
    repository, service, _ = build()
    request, _ = full_login(service)

    session = service.complete_login(request.browser_token)

    assert session.token not in repository.sessions
    assert hash_session_token(session.token) in repository.sessions
    assert all(session.token not in key for key in repository.sessions)


def test_second_login_reuses_the_same_account() -> None:
    repository, service, clock = build()
    first, _ = full_login(service)
    service.complete_login(first.browser_token)

    clock.advance(timedelta(minutes=30))
    second, _ = full_login(service)
    session = service.complete_login(second.browser_token)

    assert len(repository.users) == 1
    assert session.user.last_login_at == clock.value


def test_denied_login_never_issues_a_session() -> None:
    _, service, _ = build()
    request, _ = service.start_login(ip="10.0.0.1")
    service.handle_bot_start(telegram_token=request.telegram_token, identity=OWNER)

    service.handle_bot_decision(
        telegram_token=request.telegram_token,
        telegram_user_id=OWNER.telegram_user_id,
        approved=False,
    )

    assert service.complete_login.status(request.browser_token) == "denied"
    with pytest.raises(LoginDenied):
        service.complete_login(request.browser_token)


def test_expired_request_is_indistinguishable_from_unknown() -> None:
    _, service, clock = build()
    request, _ = service.start_login(ip="10.0.0.1")

    clock.advance(LOGIN_REQUEST_TTL + timedelta(seconds=1))

    with pytest.raises(LoginRequestExpired):
        service.complete_login.status(request.browser_token)
    with pytest.raises(LoginRequestExpired):
        service.complete_login.status("неизвестный токен")
    with pytest.raises(LoginRequestExpired):
        service.handle_bot_start(
            telegram_token=request.telegram_token, identity=OWNER
        )


def test_foreign_press_cannot_decide_someone_elses_request() -> None:
    # Поломка: без сверки telegram_user_id перехвативший ссылку входит сам.
    _, service, _ = build()
    request, _ = service.start_login(ip="10.0.0.1")
    service.handle_bot_start(telegram_token=request.telegram_token, identity=OWNER)

    with pytest.raises(LoginRequestExpired):
        service.handle_bot_decision(
            telegram_token=request.telegram_token,
            telegram_user_id=STRANGER.telegram_user_id,
            approved=True,
        )

    assert service.complete_login.status(request.browser_token) == "confirmation"


def test_second_start_does_not_reassign_a_request_in_confirmation() -> None:
    _, service, _ = build()
    request, _ = service.start_login(ip="10.0.0.1")
    service.handle_bot_start(telegram_token=request.telegram_token, identity=OWNER)

    with pytest.raises(LoginRequestExpired):
        service.handle_bot_start(
            telegram_token=request.telegram_token, identity=STRANGER
        )

    stored = service.repository.login_request_by_browser_token(request.browser_token)
    assert stored.telegram_user_id == OWNER.telegram_user_id


def test_ip_limit_answers_after_ten_unfinished_attempts() -> None:
    _, service, _ = build()

    for _ in range(LOGIN_FAILURE_LIMIT):
        service.start_login(ip="10.0.0.1")

    with pytest.raises(TooManyLoginAttempts):
        service.start_login(ip="10.0.0.1")
    # Лимит считается по IP, соседний адрес не страдает.
    assert service.start_login(ip="10.0.0.2")


def test_successful_login_frees_the_limit_for_its_own_request() -> None:
    _, service, _ = build()
    for _ in range(LOGIN_FAILURE_LIMIT - 1):
        service.start_login(ip="10.0.0.1")
    request, _ = full_login(service)

    service.complete_login(request.browser_token)

    assert service.start_login(ip="10.0.0.1")


def test_allowlist_blocks_a_confirmed_but_undisclosed_account() -> None:
    # Риск Р9: подтверждение личности в боте не означает допуска ко входу.
    _, service, _ = build(allowlist=frozenset({"999"}))
    request, _ = full_login(service)

    with pytest.raises(LoginNotAllowed):
        service.complete_login(request.browser_token)


def test_allowlist_lets_listed_account_in() -> None:
    _, service, _ = build(allowlist=frozenset({"101", "999"}))
    request, _ = full_login(service)

    assert service.complete_login(request.browser_token).user.telegram_user_id == "101"


def test_login_without_known_bot_username_is_unavailable() -> None:
    _, service, _ = build(bot_username="")

    with pytest.raises(TelegramUnavailable):
        service.start_login(ip="10.0.0.1")

    service.set_bot_username("@autopost_auth_bot")
    _, url = service.start_login(ip="10.0.0.1")
    assert url.startswith("https://t.me/autopost_auth_bot?start=autopost_login_")


def test_logout_drops_the_session_and_is_idempotent() -> None:
    _, service, _ = build()
    request, _ = full_login(service)
    session = service.complete_login(request.browser_token)

    service.logout(session.token)

    assert service.resolve_session(session.token) is None
    service.logout(session.token)
    service.logout(None)


def test_expired_session_does_not_resolve() -> None:
    _, service, clock = build()
    request, _ = full_login(service)
    session = service.complete_login(request.browser_token)

    clock.advance(SESSION_TTL + timedelta(seconds=1))

    assert service.resolve_session(session.token) is None


def test_project_ownership_hides_foreign_and_missing_projects() -> None:
    repository, service, _ = build()
    repository.owners[7] = 1
    repository.owners[8] = 2

    assert service.owns_project(user_id=1, project_id=7)
    assert not service.owns_project(user_id=1, project_id=8)
    assert not service.owns_project(user_id=1, project_id=999)
