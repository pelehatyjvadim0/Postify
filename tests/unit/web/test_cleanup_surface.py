"""Поверхность API: то, чего в контракте нет, не должно отвечать.

Старый контур импорта материалов снесён вместе с префиксом ``/api/v1``. Тест
держит границу: возвращённый эндпоинт заметен сразу, а не по чужому багу.
"""

from __future__ import annotations

import pytest

from tests.unit.web.test_api import ApiStub, client_for
from tests.unit.web.test_project_isolation import _api_routes


# Маршруты T0 из контракта: они обязаны существовать.
CONTRACT_ROUTES = (
    ("GET", "/api/projects"),
    ("POST", "/api/projects"),
    ("GET", "/api/projects/{project_id}"),
    ("PUT", "/api/projects/{project_id}"),
    ("DELETE", "/api/projects/{project_id}"),
    ("PUT", "/api/projects/{project_id}/channel"),
    ("POST", "/api/projects/{project_id}/channel/check"),
    ("DELETE", "/api/projects/{project_id}/channel"),
    ("GET", "/api/projects/{project_id}/rubrics"),
    ("POST", "/api/projects/{project_id}/rubrics"),
    ("PUT", "/api/projects/{project_id}/rubrics/{rubric_id}"),
    ("DELETE", "/api/projects/{project_id}/rubrics/{rubric_id}"),
    ("GET", "/api/projects/{project_id}/posts"),
    ("GET", "/api/projects/{project_id}/posts/{post_id}"),
    ("PATCH", "/api/projects/{project_id}/posts/{post_id}"),
    ("POST", "/api/projects/{project_id}/posts/{post_id}/approve"),
    ("POST", "/api/projects/{project_id}/posts/{post_id}/reject"),
    ("GET", "/api/projects/{project_id}/posts/{post_id}/media"),
    ("GET", "/api/projects/{project_id}/operations"),
    ("GET", "/api/projects/{project_id}/operations/{operation_id}"),
    ("GET", "/api/projects/{project_id}/publications"),
    ("POST", "/api/projects/{project_id}/publications/{delivery_id}/retry"),
)


def test_contract_routes_are_served() -> None:
    from tests.unit.web.test_api import app_for

    served = {
        (method, route.path)
        for route in _api_routes(app_for(ApiStub()))
        for method in route.methods - {"HEAD", "OPTIONS"}
    }

    assert set(CONTRACT_ROUTES) <= served


@pytest.mark.parametrize(
    ("method", "path"),
    (
        # Префикса /api/v1 больше нет.
        ("get", "/api/v1/bootstrap"),
        ("get", "/api/v1/projects/1/packages"),
        # Старый контур импорта материалов.
        ("get", "/api/bootstrap"),
        ("get", "/api/projects/1/materials"),
        ("get", "/api/projects/1/packages"),
        ("get", "/api/projects/1/queue"),
        ("get", "/api/projects/1/sources"),
        ("get", "/api/projects/1/routes"),
        ("get", "/api/projects/1/channels"),
        ("get", "/api/projects/1/settings"),
        ("get", "/api/projects/1/formats"),
    ),
)
def test_removed_endpoints_answer_404(method: str, path: str) -> None:
    response = getattr(client_for(ApiStub()), method)(path)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "path",
    (
        "/api/projects/1/operations/run-once",
        "/api/projects/1/operations/search",
    ),
)
def test_removed_operations_are_not_callable(path: str) -> None:
    # Путь совпадает с чтением операции, но POST по нему больше не существует.
    response = client_for(ApiStub()).post(path)

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
