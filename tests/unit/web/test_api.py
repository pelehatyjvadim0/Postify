from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx


NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)


class ApiStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.run_once_busy = False
        self.fail = False

    def bootstrap(self):
        return {
            "activeProject": {"id": 1, "name": "Редакция"},
            "providers": {
                "sources": [{"code": "hn_algolia", "label": "HN Algolia", "fields": []}],
                "channels": [{"code": "telegram", "label": "Telegram", "fields": []}],
            },
        }

    def dashboard(self, project_id: int):
        return {"projectId": project_id, "candidateTotal": 3}

    def materials(self, project_id: int, **filters: object):
        return {"projectId": project_id, "items": [], "filters": filters}

    def packages(self, project_id: int, **filters: object):
        return {"projectId": project_id, "items": [], "filters": filters}

    def package(self, project_id: int, package_id: int):
        return {"projectId": project_id, "id": package_id, "history": []}

    def approve(self, project_id: int, package_id: int):
        self.calls.append(("approve", (project_id, package_id)))
        return {"id": package_id, "status": "approved"}

    def reject(self, project_id: int, package_id: int, reason: str):
        self.calls.append(("reject", (project_id, package_id, reason)))
        return {"id": package_id, "status": "rejected", "reason": reason}

    def queue(self, project_id: int):
        return {"projectId": project_id, "items": []}

    def publications(self, project_id: int, **filters: object):
        return {"projectId": project_id, "items": [], "filters": filters}

    def operations(self, project_id: int, **filters: object):
        return {"projectId": project_id, "items": [], "filters": filters}

    def run_once(self, project_id: int):
        if self.run_once_busy:
            raise RuntimeError("operation_busy")
        self.calls.append(("run_once", (project_id,)))
        return {"status": "accepted"}

    def publish_once(self, project_id: int):
        self.calls.append(("publish_once", (project_id,)))
        return {"outcome": "empty"}

    def settings(self, project_id: int):
        return {
            "project": {"id": project_id, "name": "Редакция"},
            "channels": [
                {
                    "id": 2,
                    "provider": "telegram",
                    "name": "Основной",
                    "configuration": {"chat_id": "-1001"},
                    "secretConfigured": True,
                }
            ],
        }

    def update_settings(self, project_id: int, section: str, payload: dict[str, object]):
        self.calls.append(("update_settings", (project_id, section, payload)))
        return {"id": project_id, "name": payload.get("name", "Редакция")}

    def resources(self, project_id: int, resource: str):
        return {"projectId": project_id, "resource": resource, "items": []}

    def create_resource(self, project_id: int, resource: str, payload: dict[str, object]):
        self.calls.append(("create_resource", (project_id, resource, payload)))
        return {"id": 10, **payload}

    def update_resource(self, project_id: int, resource: str, resource_id: int, payload: dict[str, object]):
        self.calls.append(("update_resource", (project_id, resource, resource_id, payload)))
        return {"id": resource_id, **payload}

    def delete_resource(self, project_id: int, resource: str, resource_id: int):
        self.calls.append(("delete_resource", (project_id, resource, resource_id)))

    def check_channel(self, project_id: int, channel_id: int):
        self.calls.append(("check_channel", (project_id, channel_id)))
        return {"id": channel_id, "connectionStatus": "ok"}

    def remove_channel_secret(self, project_id: int, channel_id: int):
        self.calls.append(("remove_channel_secret", (project_id, channel_id)))
        return {"id": channel_id, "secretConfigured": False}

    def package_media(self, project_id: int, package_id: int):
        self.calls.append(("package_media", (project_id, package_id)))
        return b"image", "image/jpeg"


class ApiClient:
    def __init__(self, app) -> None:
        self._app = app
        self._cookies = httpx.Cookies()
        self._csrf_token: str | None = None

    def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                cookies=self._cookies,
            ) as client:
                if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
                    if self._csrf_token is None:
                        bootstrap = await client.get("/api/v1/bootstrap")
                        self._csrf_token = bootstrap.json()["csrfToken"]
                    headers = dict(kwargs.pop("headers", {}) or {})
                    headers.setdefault("Origin", "http://testserver")
                    headers.setdefault("X-Postify-CSRF", self._csrf_token)
                    kwargs["headers"] = headers
                response = await client.request(method, path, **kwargs)
                self._cookies.update(client.cookies)
                if path == "/api/v1/bootstrap" and response.is_success:
                    self._csrf_token = response.json()["csrfToken"]
                return response

        return asyncio.run(send())

    def get(self, path: str, **kwargs: object) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: object) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: object) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: object) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)


def client_for(stub: ApiStub) -> ApiClient:
    from postify.web.app import create_app
    from postify.web.dependencies import WebContainer

    return ApiClient(create_app(WebContainer(api=stub)))


def test_bootstrap_returns_active_project_and_registered_providers() -> None:
    # Break caught: bootstrap does not expose the active project through the API boundary.
    response = client_for(ApiStub()).get("/api/v1/bootstrap")

    assert response.status_code == 200
    assert response.json()["activeProject"]["id"] == 1
    assert response.json()["providers"]["channels"] == [
        {"code": "telegram", "label": "Telegram", "fields": []}
    ]


def test_bootstrap_response_schema_keeps_descriptor_and_drops_unknown_values() -> None:
    # Поломка final review: recursive key heuristic пропускает value
    # внутри безопасно названного credential descriptor.
    class LeakyCatalog(ApiStub):
        def bootstrap(self):
            return {
                "activeProject": {
                    "id": 1,
                    "name": "Редакция",
                    "encrypted_secret": "project-leak",
                },
                "providers": {
                    "sources": [],
                    "channels": [
                        {
                            "code": "telegram",
                            "label": "Telegram",
                            "fields": [],
                            "credential": {
                                "name": "token",
                                "label": "Токен бота",
                                "input_type": "password",
                                "value": "descriptor-leak",
                            },
                            "token": "provider-leak",
                        }
                    ],
                },
            }

    response = client_for(LeakyCatalog()).get("/api/v1/bootstrap")

    assert response.status_code == 200
    assert response.json()["providers"]["channels"] == [
        {
            "code": "telegram",
            "label": "Telegram",
            "fields": [],
            "credential": {
                "name": "token",
                "label": "Токен бота",
                "input_type": "password",
            },
        }
    ]
    assert "leak" not in response.text


def test_route_schedule_and_explicit_secret_removal_have_strict_commands() -> None:
    # Break caught: publication slots are dropped by the route schema, or clearing a token deletes the channel itself.
    stub = ApiStub()
    client = client_for(stub)
    route = client.put(
        "/api/v1/projects/1/routes/10",
        json={
            "format_id": 1,
            "channel_id": 2,
            "cta_id": 3,
            "enabled": True,
            "schedule": {
                "autopublish": True,
                "slots": ["09:00", "14:30", "19:15"],
            },
        },
    )
    removed = client.post("/api/v1/projects/1/channels/2/secret/remove")
    invalid = client.put(
        "/api/v1/projects/1/routes/10",
        json={
            "format_id": 1,
            "channel_id": 2,
            "enabled": True,
            "schedule": {"autopublish": True, "slots": ["09:00", "99:00"]},
        },
    )

    assert route.status_code == 200
    assert removed.status_code == 200
    assert invalid.status_code == 422
    assert stub.calls == [
        (
            "update_resource",
            (
                1,
                "routes",
                10,
                {
                    "format_id": 1,
                    "channel_id": 2,
                    "cta_id": 3,
                    "enabled": True,
                    "schedule": {
                        "autopublish": True,
                        "slots": ["09:00", "14:30", "19:15"],
                    },
                },
            ),
        ),
        ("remove_channel_secret", (1, 2)),
    ]


def test_optional_route_schedule_is_omitted_and_invalid_source_cron_is_rejected() -> None:
    # Поломка review: schedule=None перезатирает NOT NULL default; bad cron тихо never-due.
    stub = ApiStub()
    client = client_for(stub)

    route = client.post(
        "/api/v1/projects/1/routes",
        json={"format_id": 1, "channel_id": 2, "enabled": True},
    )
    invalid_source = client.post(
        "/api/v1/projects/1/sources",
        json={
            "provider": "hn_algolia",
            "name": "Broken cron",
            "enabled": True,
            "configuration": {},
            "schedule": "whenever convenient",
        },
    )

    assert route.status_code == 201
    assert invalid_source.status_code == 422
    assert stub.calls == [
        (
            "create_resource",
            (
                1,
                "routes",
                {"format_id": 1, "channel_id": 2, "enabled": True},
            ),
        )
    ]


def test_selection_policy_version_is_not_a_client_owned_setting() -> None:
    # Поломка review: client может подменить audit policy version.
    response = client_for(ApiStub()).put(
        "/api/v1/projects/1/settings/configuration",
        json={"selection_policy_version": "user-controlled-v999"},
    )

    assert response.status_code == 422


def test_schedule_section_is_one_strict_atomic_command() -> None:
    # Break caught: schedule persistence requires separate source/route requests or accepts invalid publication slots.
    stub = ApiStub()
    client = client_for(stub)
    payload = {
        "sources": [{"id": 1, "schedule": "0 8 * * *"}],
        "routes": [{
            "id": 10,
            "autopublish": False,
            "slots": ["08:30", "13:30", "18:30"],
        }],
    }

    updated = client.put("/api/v1/projects/1/settings/schedule", json=payload)
    invalid = client.put(
        "/api/v1/projects/1/settings/schedule",
        json={
            "sources": [],
            "routes": [{"id": 10, "autopublish": True, "slots": ["09:00", "09:00", "19:00"]}],
        },
    )

    assert updated.status_code == 200
    assert invalid.status_code == 422
    assert stub.calls == [("update_settings", (1, "schedule", payload))]


def test_settings_never_serializes_channel_secret_and_forbids_unknown_request_fields() -> None:
    # Break caught: a persistence secret reaches a GET payload or Pydantic silently accepts typoed fields.
    client = client_for(ApiStub())

    settings = client.get("/api/v1/projects/1/settings")
    invalid = client.post(
        "/api/v1/projects/1/packages/7/reject",
        json={"reason": "Не подходит", "unexpected": True},
    )

    assert settings.status_code == 200
    assert "token" not in json.dumps(settings.json()).casefold()
    assert settings.json()["channels"][0]["secretConfigured"] is True
    assert invalid.status_code == 422


def test_reject_enforces_reason_boundaries_before_calling_review_action() -> None:
    # Break caught: blank/oversized reject reasons enter package history instead of being rejected at the HTTP boundary.
    stub = ApiStub()
    client = client_for(stub)

    too_short = client.post("/api/v1/projects/1/packages/7/reject", json={"reason": "не"})
    valid = client.post("/api/v1/projects/1/packages/7/reject", json={"reason": "Не подходит"})

    assert too_short.status_code == 422
    assert valid.status_code == 200
    assert stub.calls == [("reject", (1, 7, "Не подходит"))]


def test_operations_return_accepted_and_map_duplicate_run_to_conflict() -> None:
    # Break caught: synchronous run-once blocks the request or allows a second job of the same kind.
    stub = ApiStub()
    client = client_for(stub)

    accepted = client.post("/api/v1/projects/1/operations/run-once")
    stub.run_once_busy = True
    conflict = client.post("/api/v1/projects/1/operations/run-once")

    assert accepted.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "operation_busy"


def test_invalid_review_transition_is_a_conflict_not_validation_error() -> None:
    # Break caught: a repeated review action gets reported as a malformed request instead of a state conflict.
    from postify.domain.content.models import InvalidContentTransition

    stub = ApiStub()
    client = client_for(stub)

    def invalid(project_id: int, package_id: int):
        raise InvalidContentTransition("state details must not escape")

    stub.approve = invalid
    response = client.post("/api/v1/projects/1/packages/7/approve")

    assert response.status_code == 409
    assert response.json()["code"] == "invalid_transition"
    assert "details" not in response.text


def test_all_project_commands_delegate_to_the_application_boundary() -> None:
    # Break caught: route handlers grow their own persistence/domain work instead of dispatching an application action.
    stub = ApiStub()
    client = client_for(stub)

    assert client.post("/api/v1/projects/1/packages/7/approve").status_code == 200
    assert client.post("/api/v1/projects/1/operations/publish-once").status_code == 200
    assert client.put(
        "/api/v1/projects/1/settings/main",
        json={"name": "Новая редакция", "topic": "AI", "language": "ru", "audience": "Команды", "timezone": "Europe/Moscow"},
    ).status_code == 200
    assert client.post(
        "/api/v1/projects/1/channels",
        json={"provider": "telegram", "name": "Новый", "enabled": True, "configuration": {"chat_id": "-1002"}, "token": "secret"},
    ).status_code == 201
    assert client.post("/api/v1/projects/1/channels/10/check").status_code == 200
    assert client.delete("/api/v1/projects/1/routes/10").status_code == 204

    assert [call[0] for call in stub.calls] == [
        "approve", "publish_once", "update_settings", "create_resource", "check_channel", "delete_resource"
    ]


def test_mutations_require_same_origin_session_capability_and_trusted_host() -> None:
    # Поломка review: hostile form/cross-origin page может approve/publish/remove secret.
    from postify.web.app import create_app
    from postify.web.dependencies import WebContainer

    async def exercise():
        app = create_app(WebContainer(api=ApiStub()))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            bootstrap = await client.get("/api/v1/bootstrap")
            token = bootstrap.json()["csrfToken"]
            missing = await client.post(
                "/api/v1/projects/1/packages/7/approve",
                headers={"Origin": "http://testserver"},
            )
            foreign = await client.post(
                "/api/v1/projects/1/packages/7/approve",
                headers={
                    "Origin": "https://attacker.example",
                    "X-Postify-CSRF": token,
                },
            )
            valid = await client.post(
                "/api/v1/projects/1/packages/7/approve",
                headers={
                    "Origin": "http://testserver",
                    "X-Postify-CSRF": token,
                },
            )
            hostile_host = await client.get(
                "/api/v1/bootstrap", headers={"Host": "attacker.example"}
            )
        return missing, foreign, valid, hostile_host

    missing, foreign, valid, hostile_host = asyncio.run(exercise())

    assert (missing.status_code, missing.json()["code"]) == (403, "csrf_required")
    assert (foreign.status_code, foreign.json()["code"]) == (403, "origin_rejected")
    assert valid.status_code == 200
    assert (hostile_host.status_code, hostile_host.json()["code"]) == (
        400,
        "untrusted_host",
    )


def test_unexpected_error_is_safe_service_unavailable_response(monkeypatch) -> None:
    # Break caught: database/exception internals are echoed to an API client.
    stub = ApiStub()
    client = client_for(stub)

    def broken(project_id: int):
        raise OSError("postgresql://user:very-secret@/private/path")

    monkeypatch.setattr(stub, "dashboard", broken)
    response = client.get("/api/v1/projects/1/dashboard")

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"
    assert response.json()["requestId"]
    assert "secret" not in response.text
    assert "private" not in response.text


def test_media_is_loaded_only_by_owned_package_id_without_url_proxying() -> None:
    # Break caught: a media endpoint accepts external URLs or bypasses project ownership lookup.
    stub = ApiStub()
    client = client_for(stub)

    response = client.get("/api/v1/projects/1/media/packages/7")

    assert response.status_code == 200
    assert response.content == b"image"
    assert stub.calls == [("package_media", (1, 7))]


def test_every_missing_resource_uses_stable_not_found_error_contract() -> None:
    # Break caught: repository and unmatched-route not-found paths return a framework payload or 503.
    from sqlalchemy.exc import NoResultFound

    stub = ApiStub()
    client = client_for(stub)

    def missing(project_id: int, package_id: int):
        raise NoResultFound("internal package lookup")

    stub.approve = missing
    missing_package = client.post("/api/v1/projects/1/packages/999/approve")
    missing_route = client.get("/api/v1/projects/1/unknown-resource")

    for response in (missing_package, missing_route):
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
        assert response.json()["requestId"]
        assert "internal" not in response.text
