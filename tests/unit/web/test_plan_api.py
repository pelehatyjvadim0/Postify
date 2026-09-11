"""HTTP-контракт контент-плана — раздел 7.

Проверяется то, за что отвечает веб-слой: разбор ``from``/``to``, коды ответов
и перевод отказов плана в коды контракта. Фасад подменён заглушкой.
"""

from __future__ import annotations

from datetime import UTC, datetime

from starlette.routing import Mount

from postify.domain.plan.models import (
    PostAlreadyGenerated,
    SlotTimeTaken,
    SlotTopicRequired,
)
from postify.web.routes.plan import router as plan_router
from tests.unit.web.test_api import ApiClient, ApiStub, app_for


NOW = datetime(2026, 10, 9, 18, tzinfo=UTC)


def _slot(slot_id: int = 41, status: str = "planned") -> dict[str, object]:
    return {
        "id": slot_id,
        "publish_at": NOW,
        "generate_at": datetime(2026, 10, 8, 18, tzinfo=UTC),
        "rubric": {"id": 7, "name": "Подборка"},
        "topic": "Ошибки при хранении зерна",
        "status": status,
        "post": None,
    }


class PlanStub(ApiStub):
    """Заглушка фасада с методами плана."""

    def __init__(self) -> None:
        super().__init__()
        self.plan_error: BaseException | None = None

    def _plan_call(self, name: str, *values: object) -> None:
        self.calls.append((name, values))
        if self.plan_error is not None:
            raise self.plan_error

    def plan(self, project_id, *, date_from, date_to):
        self._plan_call("plan", project_id, date_from, date_to)
        return [_slot()]

    def create_slot(self, project_id, payload):
        self._plan_call("create_slot", project_id, payload)
        return _slot()

    def update_slot(self, project_id, slot_id, payload):
        self._plan_call("update_slot", project_id, slot_id, payload)
        return _slot(slot_id)

    def delete_slot(self, project_id, slot_id):
        self._plan_call("delete_slot", project_id, slot_id)

    def generate_slot(self, project_id, slot_id):
        self._plan_call("generate_slot", project_id, slot_id)
        return {"operation_id": 1841, "status": "running"}

    def skip_slot(self, project_id, slot_id):
        self._plan_call("skip_slot", project_id, slot_id)
        return _slot(slot_id, status="skipped")


def _app(stub: PlanStub):
    """Приложение с роутером плана.

    Подключение к ``API_ROUTERS`` делает сборка; здесь роутер добавляется
    вручную и ставится перед отдачей SPA, иначе его перехватит mount на «/».
    """
    app = app_for(stub)
    added = len(app.routes)
    app.include_router(plan_router)
    new = app.routes[added:]
    del app.routes[added:]
    first_mount = next(
        (index for index, route in enumerate(app.routes) if isinstance(route, Mount)),
        len(app.routes),
    )
    app.routes[first_mount:first_mount] = new
    return app


def _client(stub: PlanStub) -> ApiClient:
    return ApiClient(_app(stub))


def test_plan_range_is_read_from_query_dates() -> None:
    stub = PlanStub()

    response = _client(stub).get("/api/projects/1/plan?from=2026-10-01&to=2026-10-31")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == 41
    assert body[0]["rubric"] == {"id": 7, "name": "Подборка"}
    name, values = stub.calls[0]
    assert name == "plan"
    assert (values[1].isoformat(), values[2].isoformat()) == ("2026-10-01", "2026-10-31")


def test_plan_requires_both_range_bounds() -> None:
    response = _client(PlanStub()).get("/api/projects/1/plan?from=2026-10-01")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_slot_crud_passes_only_the_fields_from_the_request() -> None:
    stub = PlanStub()
    client = _client(stub)

    created = client.post(
        "/api/projects/1/plan",
        json={"publish_at": "2026-10-09T18:00:00+03:00", "topic": "Тема"},
    )
    patched = client.patch("/api/projects/1/plan/41", json={"topic": "Другая"})
    deleted = client.delete("/api/projects/1/plan/41")

    assert created.status_code == 201
    assert patched.status_code == 200
    assert ("update_slot", (1, 41, {"topic": "Другая"})) in stub.calls
    assert deleted.status_code == 204
    assert deleted.content == b""


def test_patch_requires_at_least_one_field() -> None:
    response = _client(PlanStub()).patch("/api/projects/1/plan/41", json={})

    assert response.status_code == 422


def test_publication_time_must_carry_a_timezone() -> None:
    response = _client(PlanStub()).post(
        "/api/projects/1/plan", json={"publish_at": "2026-10-09T18:00:00"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "publish_at"


def test_generate_answers_202_with_the_operation_to_poll() -> None:
    stub = PlanStub()

    response = _client(stub).post("/api/projects/1/plan/41/generate")

    assert response.status_code == 202
    assert response.json() == {"operation_id": 1841, "status": "running"}
    assert ("generate_slot", (1, 41)) in stub.calls


def test_skip_returns_the_updated_slot() -> None:
    response = _client(PlanStub()).post("/api/projects/1/plan/41/skip")

    assert response.status_code == 200
    assert response.json()["status"] == "skipped"


def test_generation_without_a_topic_is_400_with_the_contract_code() -> None:
    stub = PlanStub()
    stub.plan_error = SlotTopicRequired("Тема слота не заполнена")

    response = _client(stub).post("/api/projects/1/plan/41/generate")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "slot_topic_required"
    assert response.json()["error"]["message"] == "Тема слота не заполнена"


def test_editing_the_topic_of_a_generated_slot_is_409() -> None:
    stub = PlanStub()
    stub.plan_error = PostAlreadyGenerated("Пост уже сгенерирован")

    response = _client(stub).patch("/api/projects/1/plan/41", json={"topic": "Тема"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "post_already_generated"


def test_two_slots_on_the_same_minute_are_reported_as_a_conflict() -> None:
    stub = PlanStub()
    stub.plan_error = SlotTimeTaken("На это время в плане уже есть слот")

    response = _client(stub).post(
        "/api/projects/1/plan", json={"publish_at": "2026-10-09T18:00:00+03:00"}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slot_time_taken"
