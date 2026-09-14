"""HTTP-контур входа: /api/auth/*, /api/me и проверка владения проектом."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from postify.application.auth.service import AuthService
from postify.domain.auth.models import (
    LOGIN_FAILURE_LIMIT,
    LOGIN_REQUEST_TTL,
    TelegramIdentity,
    hash_session_token,
)
from postify.web.auth import install_auth, owned_project

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "auth"))
from fakes import FakeUserRepository  # noqa: E402


ORIGIN = {"Origin": "http://testserver"}
NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
OWNER = TelegramIdentity(
    telegram_user_id="101", telegram_username="user_101", display_name="Иван Петров"
)


class Clock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        return self.value


def build_app(allowlist: frozenset[str] = frozenset()):
    repository = FakeUserRepository()
    clock = Clock()
    service = AuthService(
        repository,
        allowlist=allowlist,
        bot_username="autopost_auth_bot",
        clock=clock,
    )
    app = FastAPI()
    app.state.trusted_hosts = frozenset({"testserver"})
    install_auth(app, auth=service)

    # Заглушка чужого роутера: владение проверяет только общая зависимость.
    projects = APIRouter(prefix="/api/projects/{project_id}")

    @projects.get("/plan")
    def plan(project_id: int = Depends(owned_project)) -> dict[str, int]:
        return {"project_id": project_id}

    app.include_router(projects)
    return app, service, repository, clock


@pytest.fixture
def context():
    return build_app()


def login(client: TestClient, service, identity: TelegramIdentity = OWNER, *, approve=True):
    created = client.post("/api/auth/login", headers=ORIGIN)
    browser_token = created.json()["browser_token"]
    request = service.repository.login_request_by_browser_token(browser_token)
    service.handle_bot_start(
        telegram_token=request.telegram_token, identity=identity
    )
    service.handle_bot_decision(
        telegram_token=request.telegram_token,
        telegram_user_id=identity.telegram_user_id,
        approved=approve,
    )
    return browser_token


def test_login_returns_the_deeplink_and_hides_the_telegram_token(context) -> None:
    app, service, _, _ = context
    client = TestClient(app)

    response = client.post("/api/auth/login", headers=ORIGIN)

    body = response.json()
    assert response.status_code == 201
    assert set(body) == {"browser_token", "telegram_url", "expires_at"}
    assert body["telegram_url"].startswith("https://t.me/autopost_auth_bot?start=autopost_login_")
    assert body["expires_at"] == (NOW + LOGIN_REQUEST_TTL).isoformat()
    stored = service.repository.login_request_by_browser_token(body["browser_token"])
    # Токены разные: наружу уходит только browser_token, telegram_token живёт
    # в диплинке и отдельным полем не отдаётся.
    assert stored.browser_token != stored.telegram_token
    assert body["browser_token"] == stored.browser_token
    assert "telegram_token" not in body


def test_login_requires_matching_origin(context) -> None:
    app, _, _, _ = context
    client = TestClient(app)

    response = client.post("/api/auth/login", headers={"Origin": "https://evil.example"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "origin_rejected"


def test_status_walks_pending_confirmation_and_approved(context) -> None:
    app, service, repository, _ = context
    client = TestClient(app)
    created = client.post("/api/auth/login", headers=ORIGIN)
    browser_token = created.json()["browser_token"]
    request = repository.login_request_by_browser_token(browser_token)

    assert _status(client, browser_token).json() == {"status": "pending"}
    service.handle_bot_start(telegram_token=request.telegram_token, identity=OWNER)
    assert _status(client, browser_token).json() == {"status": "confirmation"}

    service.handle_bot_decision(
        telegram_token=request.telegram_token, telegram_user_id="101", approved=True
    )
    approved = _status(client, browser_token)

    body = approved.json()
    assert approved.status_code == 200
    assert body["status"] == "approved"
    assert body["user"]["telegram_user_id"] == "101"
    assert body["user"]["display_name"] == "Иван Петров"
    assert body["csrf"]
    cookie = approved.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Max-Age=31536000" in cookie


def test_approved_status_stores_only_the_hash_of_the_session_token(context) -> None:
    # Поломка: открытый токен в хранилище равен утечке доступа.
    app, service, repository, _ = context
    client = TestClient(app)
    browser_token = login(client, service)

    _status(client, browser_token)

    token = client.cookies["postify_session"]
    assert token not in repository.sessions
    assert hash_session_token(token) in repository.sessions


def test_second_poll_of_a_used_request_says_expired(context) -> None:
    app, service, _, _ = context
    client = TestClient(app)
    browser_token = login(client, service)

    assert _status(client, browser_token).status_code == 200
    repeated = _status(client, browser_token)

    assert repeated.status_code == 404
    assert repeated.json() == {"status": "expired"}


def test_unknown_and_expired_requests_answer_the_same(context) -> None:
    app, service, _, clock = context
    client = TestClient(app)
    created = client.post("/api/auth/login", headers=ORIGIN)
    browser_token = created.json()["browser_token"]

    clock.value = NOW + LOGIN_REQUEST_TTL + timedelta(seconds=1)

    assert _status(client, browser_token).json() == {"status": "expired"}
    assert _status(client, "нет такого").json() == {"status": "expired"}
    assert _status(client, browser_token).status_code == 404


def test_denied_login_reports_denied_and_sets_no_cookie(context) -> None:
    app, service, _, _ = context
    client = TestClient(app)
    browser_token = login(client, service, approve=False)

    response = _status(client, browser_token)

    assert response.json() == {"status": "denied"}
    assert "set-cookie" not in response.headers


def test_account_outside_the_allowlist_is_refused() -> None:
    app, service, _, _ = build_app(allowlist=frozenset({"999"}))
    client = TestClient(app)
    browser_token = login(client, service)

    response = _status(client, browser_token)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "login_not_allowed"
    assert "set-cookie" not in response.headers


def test_ip_limit_answers_429_with_retry_after(context) -> None:
    app, _, _, _ = context
    client = TestClient(app)

    for _ in range(LOGIN_FAILURE_LIMIT):
        assert client.post("/api/auth/login", headers=ORIGIN).status_code == 201
    response = client.post("/api/auth/login", headers=ORIGIN)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "300"
    assert response.json()["error"]["code"] == "too_many_login_attempts"


def test_api_without_session_answers_401_in_the_contract_format(context) -> None:
    app, _, _, _ = context
    client = TestClient(app)

    for path in ("/api/me", "/api/projects/1/plan"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "authentication_required"
        assert response.json()["error"]["message"]


def test_login_endpoints_stay_open_without_a_session(context) -> None:
    app, _, _, _ = context
    client = TestClient(app)

    assert client.post("/api/auth/login", headers=ORIGIN).status_code == 201
    assert _status(client, "нет такого").status_code == 404


def test_me_returns_the_signed_in_user(context) -> None:
    app, service, repository, _ = context
    client = TestClient(app)
    browser_token = login(client, service)
    _status(client, browser_token)
    repository.prompts[1] = "Пиши коротко"

    response = client.get("/api/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": 1,
        "telegram_user_id": "101",
        "telegram_username": "user_101",
        "display_name": "Иван Петров",
        "created_at": NOW.isoformat(),
        "common_prompt": "Пиши коротко",
    }


def test_foreign_and_missing_projects_both_answer_404(context) -> None:
    # Риск Р7: чужой проект не должен отличаться от несуществующего.
    app, service, repository, _ = context
    client = TestClient(app)
    browser_token = login(client, service)
    _status(client, browser_token)
    repository.owners[7] = 1
    repository.owners[8] = 2

    assert client.get("/api/projects/7/plan").json() == {"project_id": 7}
    foreign = client.get("/api/projects/8/plan")
    missing = client.get("/api/projects/999/plan")

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["code"] == missing.json()["error"]["code"] == "not_found"
    assert foreign.json()["error"]["message"] == missing.json()["error"]["message"]


def test_logout_drops_the_session_and_requires_csrf(context) -> None:
    app, service, _, _ = context
    client = TestClient(app)
    browser_token = login(client, service)
    csrf = _status(client, browser_token).json()["csrf"]

    without_token = client.post("/api/auth/logout", headers=ORIGIN)
    assert without_token.status_code == 400
    assert without_token.json()["error"]["code"] == "csrf_required"

    response = client.post(
        "/api/auth/logout", headers={**ORIGIN, "x-postify-csrf": csrf}
    )

    assert response.status_code == 204
    assert client.get("/api/me").status_code == 401


def _status(client: TestClient, browser_token: str):
    return client.get("/api/auth/login/status", params={"request": browser_token})


def test_me_restores_csrf_for_a_valid_session_after_restart(context):
    app, service, _, _ = context
    client = TestClient(app)
    token = login(client, service)
    original = _status(client, token).json()['csrf']
    app.state.csrf_secret = b'restarted-server-secret'
    response = client.get('/api/me')
    assert response.status_code == 200
    restored = response.headers['x-postify-csrf']
    assert restored and restored != original
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['telegram_user_id'] == OWNER.telegram_user_id
    assert client.post('/api/auth/logout', headers={**ORIGIN, 'x-postify-csrf': restored}).status_code == 204


def test_me_never_discloses_csrf_without_valid_session(context):
    app, *_ = context
    response = TestClient(app).get('/api/me')
    assert response.status_code == 401
    assert 'x-postify-csrf' not in response.headers


def test_https_me_upgrades_existing_cookie_to_secure(context):
    app, service, *_ = context
    client = TestClient(app)
    token = login(client, service)
    _status(client, token)
    response = client.get('https://testserver/api/me')
    assert response.status_code == 200
    cookie = response.headers['set-cookie'].lower()
    assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
