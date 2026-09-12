"""Вход целиком: HTTP, цикл опроса бота и PostgreSQL.

Telegram подменён транспортом httpx, сеть не трогается. Сценарий повторяет
проверочный ``check-telegram-auth.mjs`` из FakeTG.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sys
from time import monotonic, sleep

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from postify.adapters.telegram.auth_bot import (
    APPROVED_TEXT,
    DENIED_TEXT,
    FOREIGN_TEXT,
    AuthBotPoller,
    TelegramAuthBot,
)
from postify.application.auth.service import AuthService
from postify.infrastructure.repositories.sqlalchemy_users import (
    SqlAlchemyUserRepository,
)
from postify.web.auth import install_auth, owned_project

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "unit" / "adapters" / "telegram")
)
from test_auth_bot import FakeTelegram, decision_update, start_update  # noqa: E402


pytestmark = pytest.mark.integration


ORIGIN = {"Origin": "http://testserver"}
DEADLINE = 10.0


@pytest.fixture
def context(migrated_database_url: str):
    engine = create_engine(migrated_database_url)
    telegram = FakeTelegram()
    client = httpx.AsyncClient(transport=httpx.MockTransport(telegram.handler))
    repository = SqlAlchemyUserRepository(sessionmaker(engine, expire_on_commit=False))
    service = AuthService(repository, clock=lambda: datetime.now(UTC))
    poller = AuthBotPoller(
        TelegramAuthBot(client, bot_token="777:TEST"),
        service,
        poll_timeout=0,
        retry_delay=0.01,
    )
    app = FastAPI()
    app.state.trusted_hosts = frozenset({"testserver"})
    install_auth(app, auth=service, poller=poller)

    projects = APIRouter(prefix="/api/projects/{project_id}")

    @projects.get("/plan")
    def plan(project_id: int = Depends(owned_project)) -> dict[str, int]:
        return {"project_id": project_id}

    app.include_router(projects)
    try:
        yield app, telegram, engine
    finally:
        engine.dispose()


def wait_for(predicate, message: str):
    deadline = monotonic() + DEADLINE
    while monotonic() < deadline:
        value = predicate()
        if value:
            return value
        sleep(0.02)
    raise AssertionError(message)


def start_login(client: TestClient) -> tuple[str, str]:
    response = client.post("/api/auth/login", headers=ORIGIN)
    assert response.status_code == 201
    body = response.json()
    telegram_token = body["telegram_url"].rsplit("start=autopost_login_", 1)[1]
    return body["browser_token"], telegram_token


def status(client: TestClient, browser_token: str):
    return client.get("/api/auth/login/status", params={"request": browser_token})


def test_full_login_creates_the_account_and_opens_a_session(context) -> None:
    app, telegram, engine = context
    with TestClient(app) as client:
        wait_for(lambda: telegram.method_calls("getMe"), "имя бота не запрошено")
        browser_token, telegram_token = start_login(client)
        assert status(client, browser_token).json() == {"status": "pending"}

        telegram.updates.append(start_update(telegram_token, 101))
        wait_for(
            lambda: status(client, browser_token).json()["status"] == "confirmation",
            "бот не обработал /start",
        )

        # Чужое нажатие решения не принимает.
        telegram.updates.append(decision_update(telegram_token, 202, "yes"))
        wait_for(
            lambda: [
                call
                for call in telegram.method_calls("answerCallbackQuery")
                if call.get("text") == FOREIGN_TEXT
            ],
            "чужое нажатие не отклонено",
        )
        assert status(client, browser_token).json() == {"status": "confirmation"}

        telegram.updates.append(decision_update(telegram_token, 101, "yes"))
        approved = wait_for(
            lambda: (
                response
                if (response := status(client, browser_token)).json().get("status")
                == "approved"
                else None
            ),
            "вход не подтверждён",
        )

        assert approved.json()["user"]["telegram_user_id"] == "101"
        assert approved.json()["user"]["display_name"] == "Иван Петров"
        assert "HttpOnly" in approved.headers["set-cookie"]
        assert telegram.method_calls("editMessageText")[-1]["text"] == APPROVED_TEXT

        me = client.get("/api/me")
        assert me.status_code == 200
        assert me.json()["telegram_username"] == "user_101"

        # Погашенный запрос второй cookie не выдаёт.
        assert status(client, browser_token).status_code == 404

    with engine.connect() as connection:
        users = connection.execute(
            text("SELECT telegram_user_id, is_active FROM users")
        ).all()
        sessions = connection.execute(
            text("SELECT token_hash FROM user_sessions")
        ).scalars().all()
        requests = connection.execute(text("SELECT count(*) FROM login_requests")).scalar_one()

    assert users == [("101", True)]
    assert len(sessions) == 1
    assert requests == 0


def test_session_token_from_the_cookie_is_not_stored_in_the_database(context) -> None:
    app, telegram, engine = context
    with TestClient(app) as client:
        browser_token, telegram_token = start_login(client)
        telegram.updates.append(start_update(telegram_token, 101))
        wait_for(
            lambda: status(client, browser_token).json()["status"] == "confirmation",
            "бот не обработал /start",
        )
        telegram.updates.append(decision_update(telegram_token, 101, "yes"))
        wait_for(
            lambda: status(client, browser_token).json().get("status") == "approved",
            "вход не подтверждён",
        )
        token = client.cookies["postify_session"]

    with engine.connect() as connection:
        stored = connection.execute(text("SELECT token_hash FROM user_sessions")).scalars().all()

    assert token not in stored


def test_denied_login_leaves_no_user_and_no_session(context) -> None:
    app, telegram, engine = context
    with TestClient(app) as client:
        browser_token, telegram_token = start_login(client)
        telegram.updates.append(start_update(telegram_token, 303))
        wait_for(
            lambda: status(client, browser_token).json()["status"] == "confirmation",
            "бот не обработал /start",
        )

        telegram.updates.append(decision_update(telegram_token, 303, "no"))
        wait_for(
            lambda: status(client, browser_token).json()["status"] == "denied",
            "отказ не зафиксирован",
        )

        denied = status(client, browser_token)
        assert "set-cookie" not in denied.headers
        assert telegram.method_calls("editMessageText")[-1]["text"] == DENIED_TEXT
        assert client.get("/api/me").status_code == 401

    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM users")).scalar_one() == 0
        assert (
            connection.execute(text("SELECT count(*) FROM user_sessions")).scalar_one()
            == 0
        )


def test_ownership_and_logout_are_enforced_end_to_end(context) -> None:
    app, telegram, engine = context
    with TestClient(app) as client:
        browser_token, telegram_token = start_login(client)
        telegram.updates.append(start_update(telegram_token, 101))
        wait_for(
            lambda: status(client, browser_token).json()["status"] == "confirmation",
            "бот не обработал /start",
        )
        telegram.updates.append(decision_update(telegram_token, 101, "yes"))
        approved = wait_for(
            lambda: (
                response
                if (response := status(client, browser_token)).json().get("status")
                == "approved"
                else None
            ),
            "вход не подтверждён",
        )
        user_id = approved.json()["user"]["id"]
        csrf = approved.json()["csrf"]

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, telegram_user_id, telegram_username,"
                    " display_name, created_at, is_active)"
                    " VALUES (999, '999', 'stranger', 'Чужой', now(), true)"
                )
            )
            for identifier, owner in ((7, user_id), (8, 999)):
                connection.execute(
                    text(
                        "INSERT INTO content_projects (id, name, project_prompt, language,"
                        " audience, timezone, configuration, owner_id, created_at,"
                        " updated_at)"
                        " VALUES (:id, 'Проект', '', 'ru', '', 'Europe/Moscow',"
                        " '{}'::jsonb, :owner, now(), now())"
                    ),
                    {"id": identifier, "owner": owner},
                )

        assert client.get("/api/projects/7/plan").json() == {"project_id": 7}
        # Риск Р7: чужой проект неотличим от несуществующего.
        assert client.get("/api/projects/8/plan").status_code == 404
        assert client.get("/api/projects/999/plan").status_code == 404

        assert (
            client.post(
                "/api/auth/logout", headers={**ORIGIN, "x-postify-csrf": csrf}
            ).status_code
            == 204
        )
        assert client.get("/api/me").status_code == 401
        assert client.get("/api/projects/7/plan").status_code == 401

    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM user_sessions")).scalar_one()
            == 0
        )
