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
            "providers": {"sources": ["hn_algolia"], "channels": ["telegram"]},
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

    def package_media(self, project_id: int, package_id: int):
        self.calls.append(("package_media", (project_id, package_id)))
        return b"image", "image/jpeg"


class ApiClient:
    def __init__(self, app) -> None:
        self._app = app

    def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.request(method, path, **kwargs)

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
    assert response.json()["providers"]["channels"] == ["telegram"]


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
