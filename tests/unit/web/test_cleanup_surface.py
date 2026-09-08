from __future__ import annotations

import pytest

from tests.unit.web.test_api import ApiStub, client_for


@pytest.mark.parametrize(
    ("method", "path", "status_code", "code"),
    (
        ("get", "/api/v1/projects/1/dashboard", 404, "not_found"),
        ("post", "/api/v1/projects/1/packages/load-more", 405, "http_error"),
        ("post", "/api/v1/projects/1/packages/7/publish-now", 405, "http_error"),
        ("post", "/api/v1/projects/1/operations/publish-once", 405, "http_error"),
        ("post", "/api/v1/projects/1/packages/7/media/replace", 405, "http_error"),
    ),
)
def test_removed_postify_endpoints_are_unavailable(method: str, path: str, status_code: int, code: str) -> None:
    response = getattr(client_for(ApiStub()), method)(path)

    assert response.status_code == status_code
    assert response.json()["code"] == code


def test_workspace_endpoints_keep_their_project_scoped_contracts() -> None:
    class WorkspaceApi(ApiStub):
        def materials(self, project_id: int, **filters: object):
            return {"projectId": project_id, "items": [{"id": 41, "status": "received"}], "filters": filters}

        def packages(self, project_id: int, **filters: object):
            return {"projectId": project_id, "items": [{"id": 71, "status": "awaiting_review"}], "filters": filters}

        def queue(self, project_id: int):
            return {"projectId": project_id, "items": [{"packageId": 71, "scheduledAt": "2026-09-05T10:00:00Z"}]}

        def publications(self, project_id: int, **filters: object):
            return {"projectId": project_id, "items": [{"packageId": 71, "outcome": "published"}], "filters": filters}

        def operations(self, project_id: int, **filters: object):
            return {"projectId": project_id, "items": [{"runId": 17, "outcome": "completed"}], "filters": filters}

    client = client_for(WorkspaceApi())

    materials = client.get("/api/v1/projects/1/materials?status=received&limit=7")
    packages = client.get("/api/v1/projects/1/packages?status=awaiting_review&limit=7")
    queue = client.get("/api/v1/projects/1/queue")
    publications = client.get("/api/v1/projects/1/publications?limit=7")
    operations = client.get("/api/v1/projects/1/operations?limit=7")
    settings = client.get("/api/v1/projects/1/settings")

    assert materials.json() == {"projectId": 1, "items": [{"id": 41, "status": "received"}], "filters": {"status": "received", "query": None, "limit": 7, "offset": 0}}
    assert packages.json() == {"projectId": 1, "items": [{"id": 71, "status": "awaiting_review"}], "filters": {"status": "awaiting_review", "limit": 7, "offset": 0}}
    assert queue.json() == {"projectId": 1, "items": [{"packageId": 71, "scheduledAt": "2026-09-05T10:00:00Z"}]}
    assert publications.json() == {"projectId": 1, "items": [{"packageId": 71, "outcome": "published"}], "filters": {"limit": 7, "offset": 0}}
    assert operations.json() == {"projectId": 1, "items": [{"runId": 17, "outcome": "completed"}], "filters": {"limit": 7, "offset": 0}}
    assert settings.json()["project"] == {"id": 1, "name": "Редакция"}
