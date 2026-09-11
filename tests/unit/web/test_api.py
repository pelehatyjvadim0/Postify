"""Контракт HTTP-слоя: маршруты, коды ответов и формат ошибки.

Фасад подменён заглушкой, поэтому тесты проверяют ровно то, за что отвечает
веб-слой: разбор запроса, вызов нужного действия и форму ответа.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from postify.domain.auth.models import User
from postify.web.errors import ConflictError
from postify.web.security import CSRF_HEADER, SESSION_COOKIE, csrf_token


NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
SESSION = "test-session-token"
OWNER = User(1, "101", "user_101", "Иван Петров", NOW, NOW, True)


class AuthStub:
    """Сервис входа без базы: одна сессия и явный список своих проектов."""

    def __init__(self, *, owned: tuple[int, ...] = (1, 3)) -> None:
        self._owned = frozenset(owned)

    def resolve_session(self, token: str | None) -> User | None:
        return OWNER if token == SESSION else None

    def owns_project(self, *, user_id: int, project_id: int) -> bool:
        return user_id == OWNER.id and project_id in self._owned


def _project(project_id: int = 1) -> dict[str, object]:
    return {
        "id": project_id,
        "name": "Агротех",
        "timezone": "Europe/Moscow",
        "language": "ru",
        "audience": "Фермеры",
        "tone": "Нейтральный",
        "project_prompt": "",
        "publication_mode": "review",
        "generation_lead_minutes": 1440,
        "media_reuse_days": 30,
        "channel": {
            "configured": True,
            "chat_id": "@agrotech",
            "status": "ok",
            "checked_at": NOW,
        },
        "media": {"total": 0, "available": 0},
    }


def _post(post_id: int = 77, status: str = "needs_review") -> dict[str, object]:
    return {
        "id": post_id,
        "slot_id": None,
        "status": status,
        "post_text": "Текст поста",
        "char_count": 11,
        "scheduled_at": NOW,
        "media": {"url": f"/api/projects/1/posts/{post_id}/media", "mime": "image/jpeg"},
        "generation": {"provider": "codex", "model": "gpt-5.6-terra"},
        "validation": None,
        "delivery": None,
        "published": None,
        "history": [{"status": "needs_review", "reason": "generated", "created_at": NOW}],
        "created_at": NOW,
        "updated_at": NOW,
    }


class ApiStub:
    """Фасад приложения без базы: запоминает вызовы и отдаёт готовые ответы."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.error: BaseException | None = None

    def _record(self, name: str, *values: object) -> None:
        self.calls.append((name, values))
        if self.error is not None:
            raise self.error

    def scheduler_tick(self) -> tuple[()]:
        return ()

    def close(self) -> None:
        self._record("close")

    # --- проекты ---

    def list_projects(self, *, owner_id):
        self._record("list_projects", owner_id)
        return [
            {
                "id": 1,
                "name": "Агротех",
                "channel_title": "@agrotech",
                "publication_mode": "review",
                "counts": {"needs_review": 1},
            }
        ]

    def create_project(self, payload, *, owner_id):
        self._record("create_project", payload, owner_id)
        return _project()

    def project(self, project_id):
        self._record("project", project_id)
        return _project(project_id)

    def update_project(self, project_id, payload):
        self._record("update_project", project_id, payload)
        return _project(project_id)

    def delete_project(self, project_id):
        self._record("delete_project", project_id)

    # --- канал ---

    def set_channel(self, project_id, *, bot_token, chat_id):
        self._record("set_channel", project_id, bot_token, chat_id)
        return {
            "configured": True,
            "chat_id": chat_id,
            "status": "configured",
            "checked_at": None,
        }

    def check_channel(self, project_id):
        self._record("check_channel", project_id)
        return {
            "configured": True,
            "chat_id": "@agrotech",
            "status": "ok",
            "checked_at": NOW,
        }

    def remove_channel(self, project_id):
        self._record("remove_channel", project_id)

    # --- рубрики ---

    def rubrics(self, project_id):
        self._record("rubrics", project_id)
        return [{"id": 5, "name": "Кейс", "instructions": "Как есть", "enabled": True}]

    def create_rubric(self, project_id, payload):
        self._record("create_rubric", project_id, payload)
        return {"id": 5, "name": payload["name"], "instructions": payload["instructions"], "enabled": payload["enabled"]}

    def update_rubric(self, project_id, rubric_id, payload):
        self._record("update_rubric", project_id, rubric_id, payload)
        return {"id": rubric_id, "name": "Кейс", "instructions": "Как есть", "enabled": payload.get("enabled", True)}

    def delete_rubric(self, project_id, rubric_id):
        self._record("delete_rubric", project_id, rubric_id)

    # --- посты ---

    def posts(self, project_id, *, status=None, limit=50, offset=0):
        self._record("posts", project_id, status, limit, offset)
        return [
            {
                "id": 77,
                "status": "needs_review",
                "excerpt": "Текст поста",
                "char_count": 11,
                "media_available": True,
                "scheduled_at": NOW,
                "delivery_status": None,
                "created_at": NOW,
                "updated_at": NOW,
            }
        ]

    def post(self, project_id, post_id):
        self._record("post", project_id, post_id)
        return _post(post_id)

    def update_post(self, project_id, post_id, *, post_text=None, scheduled_at=None):
        self._record("update_post", project_id, post_id, post_text, scheduled_at)
        return _post(post_id)

    def approve_post(self, project_id, post_id):
        self._record("approve_post", project_id, post_id)
        return _post(post_id, status="approved")

    def reject_post(self, project_id, post_id):
        self._record("reject_post", project_id, post_id)
        return _post(post_id, status="rejected")

    def post_media(self, project_id, post_id):
        self._record("post_media", project_id, post_id)
        return b"image-bytes", "image/jpeg"

    # --- журнал и публикации ---

    def operations(self, project_id, *, limit=50, offset=0):
        self._record("operations", project_id, limit, offset)
        return [self.operation(project_id, 1841)]

    def operation(self, project_id, operation_id):
        self._record("operation", project_id, operation_id)
        return {
            "operation_id": operation_id,
            "purpose": "publish_once",
            "status": "succeeded",
            "actor": "user",
            "mode": "manual",
            "outcome": "published",
            "result": {"post_id": 77},
            "error": None,
            "started_at": NOW,
            "finished_at": NOW,
        }

    def publications(self, project_id, *, limit=50, offset=0):
        self._record("publications", project_id, limit, offset)
        return [
            {
                "delivery_id": 9,
                "post_id": 77,
                "provider": "telegram",
                "status": "published",
                "attempt_count": 1,
                "message_id": 12,
                "failure_code": None,
                "failure_reason": None,
                "sending_started_at": NOW,
                "confirmed_at": NOW,
                "created_at": NOW,
                "updated_at": NOW,
                "attempts": [
                    {
                        "attempt_no": 1,
                        "outcome": "published",
                        "code": None,
                        "reason": None,
                        "message_id": 12,
                        "started_at": NOW,
                        "finished_at": NOW,
                    }
                ],
            }
        ]

    def retry_delivery(self, project_id, delivery_id):
        self._record("retry_delivery", project_id, delivery_id)
        return {"operation_id": 1841, "status": "running"}


class ApiClient:
    """Клиент вошедшего пользователя: сессионная cookie, CSRF и Origin."""

    def __init__(self, app, *, session: str | None = SESSION) -> None:
        self._app = app
        self._session = session

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        cookies = {} if self._session is None else {SESSION_COOKIE: self._session}
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers.setdefault("Origin", "http://testserver")
            if self._session is not None:
                headers.setdefault(
                    CSRF_HEADER,
                    csrf_token(self._app.state.csrf_secret, self._session),
                )

        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver", cookies=cookies
            ) as client:
                return await client.request(method, path, headers=headers, **kwargs)

        return asyncio.run(send())

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs) -> httpx.Response:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)


def app_for(stub: ApiStub, *, auth: AuthStub | None = None):
    """Приложение с подставленным сервисом входа вместо настоящей базы."""
    from postify.web.app import create_app
    from postify.web.dependencies import WebContainer

    return create_app(WebContainer(api=stub), auth=auth or AuthStub())


def client_for(stub: ApiStub) -> ApiClient:
    return ApiClient(app_for(stub))


def test_projects_collection_lists_and_creates() -> None:
    stub = ApiStub()
    client = client_for(stub)

    listed = client.get("/api/projects")
    created = client.post(
        "/api/projects", json={"name": "Агротех", "timezone": "Europe/Moscow"}
    )

    assert listed.status_code == 200
    assert listed.json() == [
        {
            "id": 1,
            "name": "Агротех",
            "channel_title": "@agrotech",
            "publication_mode": "review",
            "counts": {"needs_review": 1},
        }
    ]
    assert created.status_code == 201
    assert created.json()["timezone"] == "Europe/Moscow"
    assert ("list_projects", (OWNER.id,)) in stub.calls
    assert (
        "create_project",
        ({"name": "Агротех", "timezone": "Europe/Moscow"}, OWNER.id),
    ) in stub.calls


def test_project_read_update_delete() -> None:
    stub = ApiStub()
    client = client_for(stub)

    read = client.get("/api/projects/3")
    updated = client.put("/api/projects/3", json={"tone": "Дружелюбный"})
    deleted = client.delete("/api/projects/3")

    assert read.status_code == 200
    assert read.json()["id"] == 3
    assert updated.status_code == 200
    # Частичная правка не должна дописывать в действие None-поля.
    assert ("update_project", (3, {"tone": "Дружелюбный"})) in stub.calls
    assert deleted.status_code == 204
    assert deleted.content == b""


def test_channel_accepts_token_and_never_returns_it() -> None:
    stub = ApiStub()
    client = client_for(stub)

    saved = client.put(
        "/api/projects/1/channel",
        json={"bot_token": "secret-token", "chat_id": "@agrotech"},
    )
    checked = client.post("/api/projects/1/channel/check")
    removed = client.delete("/api/projects/1/channel")

    assert saved.status_code == 200
    assert saved.json() == {
        "configured": True,
        "chat_id": "@agrotech",
        "status": "configured",
        "checked_at": None,
    }
    assert "secret-token" not in saved.text
    assert ("set_channel", (1, "secret-token", "@agrotech")) in stub.calls
    assert checked.status_code == 200
    assert checked.json()["status"] == "ok"
    assert removed.status_code == 204


def test_rubrics_crud() -> None:
    stub = ApiStub()
    client = client_for(stub)

    listed = client.get("/api/projects/1/rubrics")
    created = client.post(
        "/api/projects/1/rubrics", json={"name": "Кейс", "instructions": "Как есть"}
    )
    updated = client.put("/api/projects/1/rubrics/5", json={"enabled": False})
    deleted = client.delete("/api/projects/1/rubrics/5")

    assert listed.json() == [
        {"id": 5, "name": "Кейс", "instructions": "Как есть", "enabled": True}
    ]
    assert created.status_code == 201
    assert (
        "create_rubric",
        (1, {"name": "Кейс", "instructions": "Как есть", "enabled": True}),
    ) in stub.calls
    assert updated.status_code == 200
    assert ("update_rubric", (1, 5, {"enabled": False})) in stub.calls
    assert deleted.status_code == 204


def test_posts_reading_and_editorial_actions() -> None:
    stub = ApiStub()
    client = client_for(stub)

    listed = client.get("/api/projects/1/posts?status=needs_review&limit=10")
    read = client.get("/api/projects/1/posts/77")
    edited = client.patch(
        "/api/projects/1/posts/77",
        json={"post_text": "Новый текст", "scheduled_at": "2026-10-09T18:00:00+03:00"},
    )
    approved = client.post("/api/projects/1/posts/77/approve")
    rejected = client.post("/api/projects/1/posts/77/reject")

    assert listed.status_code == 200
    assert listed.json()[0]["id"] == 77
    assert ("posts", (1, "needs_review", 10, 0)) in stub.calls
    assert read.json()["post_text"] == "Текст поста"
    assert read.json()["media"]["url"] == "/api/projects/1/posts/77/media"
    assert edited.status_code == 200
    edit_call = next(call for name, call in stub.calls if name == "update_post")
    assert edit_call[:3] == (1, 77, "Новый текст")
    assert edit_call[3] == datetime.fromisoformat("2026-10-09T18:00:00+03:00")
    assert approved.json()["status"] == "approved"
    assert rejected.json()["status"] == "rejected"


def test_patch_post_requires_at_least_one_field() -> None:
    response = client_for(ApiStub()).patch("/api/projects/1/posts/77", json={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_patch_post_requires_timezone_in_schedule() -> None:
    response = client_for(ApiStub()).patch(
        "/api/projects/1/posts/77", json={"scheduled_at": "2026-10-09T18:00:00"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "scheduled_at"


def test_post_media_returns_file_bytes() -> None:
    response = client_for(ApiStub()).get("/api/projects/1/posts/77/media")

    assert response.status_code == 200
    assert response.content == b"image-bytes"
    assert response.headers["content-type"] == "image/jpeg"


def test_operations_publications_and_retry() -> None:
    stub = ApiStub()
    client = client_for(stub)

    operations = client.get("/api/projects/1/operations?limit=10")
    operation = client.get("/api/projects/1/operations/1841")
    publications = client.get("/api/projects/1/publications")
    retried = client.post("/api/projects/1/publications/9/retry")

    assert operations.status_code == 200
    assert operation.json()["operation_id"] == 1841
    assert operation.json()["purpose"] == "publish_once"
    assert publications.json()[0]["delivery_id"] == 9
    assert retried.status_code == 202
    assert retried.json() == {"operation_id": 1841, "status": "running"}
    assert ("retry_delivery", (1, 9)) in stub.calls


def test_unknown_body_field_is_rejected_with_field_name() -> None:
    response = client_for(ApiStub()).post(
        "/api/projects", json={"name": "Агротех", "timezone": "UTC", "owner": 2}
    )

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["field"] == "owner"
    assert body["message"]


def test_mutation_requires_origin_and_csrf_header() -> None:
    stub = ApiStub()
    app = app_for(stub)
    без_csrf = ApiClient(app, session=None)

    без_origin = ApiClient(app).post(
        "/api/projects/1/posts/77/approve", headers={"Origin": "http://evil.test"}
    )
    без_токена = без_csrf.post("/api/projects/1/posts/77/approve")

    assert без_origin.status_code == 400
    assert без_origin.json()["error"]["code"] == "origin_rejected"
    assert без_токена.status_code == 400
    assert без_токена.json()["error"]["code"] == "csrf_required"
    assert stub.calls == []


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    (
        (LookupError(77), 404, "not_found"),
        (RuntimeError("operation_busy"), 409, "operation_busy"),
        (ConflictError("delivery_not_retryable"), 409, "delivery_not_retryable"),
        (ValueError("Назначьте время в будущем"), 422, "validation_error"),
        (RuntimeError("boom"), 500, "internal_error"),
    ),
)
def test_errors_use_the_contract_envelope(
    error: BaseException, status_code: int, code: str
) -> None:
    stub = ApiStub()
    stub.error = error

    response = client_for(stub).get("/api/projects/1/posts/77")

    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert body["error"]["request_id"]
    # Тело исключения не должно утекать в ответ вместо человеческого текста.
    assert "Traceback" not in body["error"]["message"]


def test_domain_message_reaches_the_user() -> None:
    stub = ApiStub()
    stub.error = ValueError("Назначьте время в будущем")

    response = client_for(stub).get("/api/projects/1/posts/77")

    assert response.json()["error"]["message"] == "Назначьте время в будущем"
