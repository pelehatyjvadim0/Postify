"""Изоляция данных: чужой проект отвечает 404, а не 403 и не данными.

Проверка владения живёт в общей зависимости, а не в обработчиках. Поэтому
тесты идут по всем маршрутам с ``project_id`` сразу: новый эндпоинт без
проверки должен ронять этот файл, а не ждать ручного ревью (риск Р7).
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from postify.web.auth import owned_project
from tests.unit.web.test_api import ApiClient, ApiStub, AuthStub, app_for


FOREIGN_PROJECT = 2
OWN_PROJECT = 1


def _api_routes(app) -> tuple[APIRoute, ...]:
    """Все эндпоинты приложения, включая подключённые роутеры."""
    routes: list[APIRoute] = []
    for item in app.routes:
        for route in getattr(getattr(item, "original_router", None), "routes", [item]):
            if isinstance(route, APIRoute):
                routes.append(route)
    return tuple(routes)


def _scoped_routes(app) -> tuple[APIRoute, ...]:
    return tuple(
        route for route in _api_routes(app) if "{project_id}" in route.path
    )


def _project_routes(app) -> tuple[tuple[str, str], ...]:
    return tuple(
        (method, route.path)
        for route in _scoped_routes(app)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"})
    )


def _guarded(route: APIRoute) -> bool:
    return any(item.call is owned_project for item in route.dependant.dependencies)


def _path(template: str, project_id: int) -> str:
    path = template.replace("{project_id}", str(project_id))
    for name in ("post_id", "rubric_id", "slot_id", "delivery_id", "operation_id"):
        path = path.replace("{" + name + "}", "7")
    return path


def test_every_project_route_declares_the_ownership_dependency() -> None:
    app = app_for(ApiStub())

    scoped = _scoped_routes(app)

    assert scoped, "маршруты с project_id не найдены"
    unguarded = [route.path for route in scoped if not _guarded(route)]
    assert unguarded == []


def test_foreign_project_is_answered_with_404_and_no_data() -> None:
    stub = ApiStub()
    app = app_for(stub, auth=AuthStub(owned=(OWN_PROJECT,)))
    client = ApiClient(app)

    routes = _project_routes(app)
    assert len(routes) >= 16

    for method, template in routes:
        response = client.request(
            method, _path(template, FOREIGN_PROJECT), json={}
        )

        assert response.status_code == 404, (method, template)
        body = response.json()
        assert body == {
            "error": {
                "code": "not_found",
                "message": body["error"]["message"],
                "request_id": body["error"]["request_id"],
            }
        }, (method, template)
    # Ни одно действие фасада не должно было выполниться для чужого проекта.
    assert stub.calls == []


def test_own_project_is_served() -> None:
    client = ApiClient(app_for(ApiStub(), auth=AuthStub(owned=(OWN_PROJECT,))))

    assert client.get(f"/api/projects/{OWN_PROJECT}").status_code == 200
    assert client.get(f"/api/projects/{OWN_PROJECT}/rubrics").status_code == 200


@pytest.mark.parametrize(
    "path", ("/api/projects", f"/api/projects/{OWN_PROJECT}/posts")
)
def test_without_session_api_answers_401(path: str) -> None:
    # Проверку сессии ставит install_auth: убедимся, что create_app её включает.
    client = ApiClient(app_for(ApiStub()), session=None)

    response = client.get(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
