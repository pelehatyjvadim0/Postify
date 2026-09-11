"""Общий промпт пользователя в API и отсутствие системного промпта в нём.

Проверяется ровно веб-слой: хранилище подменено памятью. Системный промпт
сервера в API не появляется ни в каком виде — это раздел 13 контракта.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json

import httpx

from postify.domain.auth.models import User
from postify.web.security import CSRF_HEADER, SESSION_COOKIE, csrf_token


NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
SYSTEM_PROMPT = "СЕКРЕТНЫЙ СИСТЕМНЫЙ ПРОМПТ СЕРВЕРА"
SESSIONS = {
    "session-a": User(1, "101", "user_101", "Иван Петров", NOW, NOW, True),
    "session-b": User(2, "202", "user_202", "Пётр Иванов", NOW, NOW, True),
}


class MemoryPrompts:
    """Оба уровня промптов в памяти: тот же контракт, что у SQLAlchemy-версии."""

    def __init__(self) -> None:
        self.system = SYSTEM_PROMPT
        self.common: dict[int, str] = {}

    def system_prompt(self) -> str:
        return self.system

    def set_system_prompt(self, prompt: str, *, now: datetime) -> str:
        self.system = prompt
        return prompt

    def common_prompt(self, user_id: int) -> str:
        return self.common.get(user_id, "")

    def set_common_prompt(self, user_id: int, prompt: str, *, now: datetime) -> str:
        self.common[user_id] = prompt
        return prompt


class AuthStub:
    """Сервис входа без базы: сессия по токену, промпты из того же хранилища."""

    def __init__(self, repository: MemoryPrompts) -> None:
        self.repository = repository

    def resolve_session(self, token: str | None) -> User | None:
        return SESSIONS.get(token or "")

    def owns_project(self, *, user_id: int, project_id: int) -> bool:
        return False


class ApiStub:
    """Фасад приложения не участвует: промпты до него не доходят."""

    def scheduler_tick(self) -> tuple[()]:
        return ()

    def close(self) -> None:
        return None


def build_app() -> tuple[object, MemoryPrompts]:
    from starlette.routing import Mount

    from postify.web.app import create_app
    from postify.web.dependencies import WebContainer
    from postify.web.routes import prompts

    repository = MemoryPrompts()
    app = create_app(WebContainer(api=ApiStub()), auth=AuthStub(repository))
    # Роутер промптов подключает сборка (web/routes/__init__.py); здесь он
    # включается вручную, чтобы тест не зависел от порядка слияния треков.
    # Отдача SPA смонтирована на «/» и перехватывает всё, что объявлено после
    # неё, поэтому монтирования переставляются в конец.
    app.include_router(prompts.router)
    mounts = [route for route in app.router.routes if isinstance(route, Mount)]
    app.router.routes[:] = [
        route for route in app.router.routes if not isinstance(route, Mount)
    ] + mounts
    app.state.prompts = repository
    return app, repository


def request(app, method: str, path: str, *, session: str | None, **kwargs):
    headers = dict(kwargs.pop("headers", {}) or {})
    cookies = {} if session is None else {SESSION_COOKIE: session}
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        headers.setdefault("Origin", "http://testserver")
        if session is not None:
            headers.setdefault(CSRF_HEADER, csrf_token(app.state.csrf_secret, session))

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver", cookies=cookies
        ) as client:
            return await client.request(method, path, headers=headers, **kwargs)

    return asyncio.run(send())


def test_prompt_is_saved_and_returned_with_the_profile() -> None:
    app, repository = build_app()

    saved = request(
        app, "PUT", "/api/me/prompt", session="session-a", json={"prompt": "Без воды."}
    )
    profile = request(app, "GET", "/api/me", session="session-a")

    assert saved.status_code == 200
    assert saved.json() == {"common_prompt": "Без воды."}
    assert profile.json()["common_prompt"] == "Без воды."
    assert repository.common[1] == "Без воды."


def test_common_prompt_is_isolated_between_users() -> None:
    # Поломка: промпт кладётся в общую настройку, и указания одного
    # пользователя уезжают в посты другого.
    app, _ = build_app()

    request(
        app, "PUT", "/api/me/prompt", session="session-a", json={"prompt": "Мой стиль"}
    )
    request(
        app, "PUT", "/api/me/prompt", session="session-b", json={"prompt": "Чужой стиль"}
    )

    mine = request(app, "GET", "/api/me", session="session-a").json()
    other = request(app, "GET", "/api/me", session="session-b").json()

    assert mine["common_prompt"] == "Мой стиль"
    assert other["common_prompt"] == "Чужой стиль"


def test_prompt_requires_a_session() -> None:
    app, repository = build_app()

    # Чужой токен проходит защиту от CSRF, но сессии за ним нет.
    unknown = request(
        app, "PUT", "/api/me/prompt", session="session-x", json={"prompt": "X"}
    )
    anonymous = request(app, "PUT", "/api/me/prompt", session=None, json={"prompt": "X"})

    assert unknown.status_code == 401
    assert anonymous.status_code >= 400
    assert repository.common == {}


def test_unknown_fields_are_rejected() -> None:
    app, repository = build_app()

    response = request(
        app,
        "PUT",
        "/api/me/prompt",
        session="session-a",
        json={"prompt": "Текст", "system_prompt": "Подмена"},
    )

    assert response.status_code == 422
    assert repository.system == SYSTEM_PROMPT


def test_system_prompt_never_leaves_the_api() -> None:
    # Системный промпт — уровень разработчика: ни один маршрут не отдаёт его
    # и не принимает (раздел 13 контракта).
    app, _ = build_app()

    paths = [getattr(route, "path", "") for route in app.routes]
    schema = json.dumps(app.openapi(), ensure_ascii=False)
    profile = request(app, "GET", "/api/me", session="session-a")
    saved = request(
        app, "PUT", "/api/me/prompt", session="session-a", json={"prompt": "Мой стиль"}
    )
    read_attempt = request(app, "GET", "/api/me/prompt", session="session-a")

    assert not [path for path in paths if "system" in path]
    assert "system_prompt" not in schema
    assert SYSTEM_PROMPT not in profile.text
    assert SYSTEM_PROMPT not in saved.text
    # Чтения промпта нет: у /api/me/prompt объявлен только PUT.
    assert read_attempt.status_code >= 400
