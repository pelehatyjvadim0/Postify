"""Feature round trips through HTTP, application services and PostgreSQL."""

from datetime import timedelta
import json

import pytest

from postify.infrastructure.repositories.sqlalchemy_prompts import SqlAlchemyPromptRepository
from tests.integration.test_generation_delivery_workflow import (
    NOW, _upload_image, _wait_operation, workflow,
)


pytestmark = pytest.mark.integration


def test_rubric_and_plan_lifecycle(workflow):
    client, *_ = workflow
    rubric = client.post("/api/projects/1/rubrics", json={"name": "Совет", "instructions": "Один совет"})
    assert rubric.status_code == 201
    rubric_id = rubric.json()["id"]
    updated = client.put(f"/api/projects/1/rubrics/{rubric_id}", json={"instructions": "Два совета", "enabled": False})
    assert updated.status_code == 200 and updated.json()["enabled"] is False
    assert client.put(f"/api/projects/1/rubrics/{rubric_id}", json={"enabled": True}).status_code == 200
    day = NOW + timedelta(days=3)
    created = client.post("/api/projects/1/plan", json={"publish_at": day.isoformat(), "topic": "Хранение зерна", "rubric_id": rubric_id})
    assert created.status_code == 201, created.text
    slot_id = created.json()["id"]
    changed = client.patch(f"/api/projects/1/plan/{slot_id}", json={"topic": "Подготовка силосов", "publish_at": (day + timedelta(hours=1)).isoformat()})
    assert changed.status_code == 200
    plan = client.get("/api/projects/1/plan", params={"from": day.date().isoformat(), "to": day.date().isoformat()})
    assert plan.status_code == 200 and plan.json()[0]["topic"] == "Подготовка силосов"
    skipped = client.post(f"/api/projects/1/plan/{slot_id}/skip")
    assert skipped.status_code == 200 and skipped.json()["status"] == "skipped"
    assert client.delete(f"/api/projects/1/plan/{slot_id}").status_code == 204
    assert client.delete(f"/api/projects/1/rubrics/{rubric_id}").status_code == 204
    assert client.get("/api/projects/1/rubrics").json() == []
    assert client.post("/api/projects/1/plan", json={"topic": "Без таймзоны", "publish_at": "2026-10-12T12:00:00"}).status_code == 422


def test_media_search_toggle_recaption_and_delete(workflow):
    client, _, _, provider, *_ = workflow
    asset_id = _upload_image(client, provider)
    asset = client.get("/api/projects/1/media").json()["items"][0]
    assert client.get(asset["url"]).status_code == 200
    assert client.get(asset["thumb_url"]).status_code == 200
    changed = client.patch(f"/api/projects/1/media/{asset_id}", json={"caption": "Уникальный силос E2E", "enabled": False})
    assert changed.status_code == 200
    assert client.get("/api/projects/1/media", params={"available": True}).json()["items"] == []
    found = client.get("/api/projects/1/media", params={"q": "Уникальный"})
    assert len(found.json()["items"]) == 1
    assert client.patch(f"/api/projects/1/media/{asset_id}", json={"enabled": True}).status_code == 200
    recaption = client.post(f"/api/projects/1/media/{asset_id}/recaption")
    assert recaption.status_code == 202
    _wait_operation(client, recaption.json()["operation_id"])
    assert client.get("/api/projects/1/media").json()["items"][0]["caption"] == "Силосы для хранения зерна"
    assert client.delete(f"/api/projects/1/media/{asset_id}").status_code == 204
    assert client.get(asset["url"]).status_code == 404
    invalid = client.post("/api/projects/1/media", files={"files": ("bad.png", b"not an image", "image/png")})
    assert invalid.status_code == 202
    operation = _wait_operation(client, invalid.json()["operation_id"], expected_status="failed")
    assert operation["error"]["code"] == "caption_media_failed"
    assert client.get("/api/projects/1/media").json()["items"] == []


def test_rule_derivation_and_manual_replacement(workflow, monkeypatch):
    client, _, _, provider, *_ = workflow
    original = provider.complete

    def complete(prompt, *, output_schema=None, **kwargs):
        if "rules" in (output_schema or {}).get("properties", {}):
            return json.dumps({"rules": [{"text": "Без обещаний дохода", "severity": "block"}]})
        return original(prompt, output_schema=output_schema, **kwargs)

    monkeypatch.setattr(provider, "complete", complete)
    response = client.post("/api/projects/1/rules/derive")
    assert response.status_code == 202
    proposal = _wait_operation(client, response.json()["operation_id"])
    assert proposal["result"]
    assert client.get("/api/projects/1/rules").json() == []
    rules = [{"text": "Без обещаний дохода", "severity": "block", "origin": "derived"},
             {"text": "Вопрос в конце", "severity": "warn", "enabled": False}]
    saved = client.put("/api/projects/1/rules", json={"rules": rules})
    assert saved.status_code == 200
    assert [item["severity"] for item in client.get("/api/projects/1/rules").json()] == ["block", "warn"]
    assert client.put("/api/projects/1/rules", json={"rules": []}).status_code == 200


def test_common_prompt_and_operation_journals(workflow):
    client, api, *_ = workflow
    client._app.state.prompts = SqlAlchemyPromptRepository(api._sessions)
    updated = client.put("/api/me/prompt", json={"prompt": "Пиши по-русски"})
    assert updated.status_code == 200 and updated.json()["common_prompt"] == "Пиши по-русски"
    assert client.get("/api/projects/1/operations", params={"limit": 1, "offset": 0}).status_code == 200
    assert client.get("/api/projects/1/publications", params={"limit": 1, "offset": 0}).json() == []
    assert client.get("/api/projects/2/operations").status_code == 404
    assert client.get("/api/projects/1/operations/999999").status_code == 404
    assert client.get("/api/projects/1/operations", params={"limit": 101}).status_code == 422


def test_manual_edit_does_not_accept_a_number_inside_another_number(workflow):
    client, _, _, provider, *_ = workflow
    _upload_image(client, provider)
    created = client.post("/api/projects/1/plan", json={"topic": "Хранение зерна. Цена: 130 рублей.",
        "publish_at": (NOW + timedelta(days=2)).isoformat()})
    slot_id = created.json()["id"]
    generated = client.post(f"/api/projects/1/plan/{slot_id}/generate")
    post_id = _wait_operation(client, generated.json()["operation_id"])["result"]["post_id"]
    edited = client.patch(f"/api/projects/1/posts/{post_id}", json={"post_text": "Цена: 30 рублей."})
    assert edited.status_code == 200
    approval = client.post(f"/api/projects/1/posts/{post_id}/approve")
    assert (edited.json()["validation"]["passed"], approval.status_code) == (False, 409), {
        "validation": edited.json()["validation"], "approval_status": approval.status_code,
    }


def test_approval_requires_current_validation(workflow):
    client, _, engine, provider, *_ = workflow
    _upload_image(client, provider)
    slot = client.post('/api/projects/1/plan', json={'topic': 'Хранение зерна',
        'publish_at': (NOW + timedelta(days=2)).isoformat()}).json()['id']
    generated = client.post(f'/api/projects/1/plan/{slot}/generate')
    post = _wait_operation(client, generated.json()['operation_id'])['result']['post_id']
    from sqlalchemy import text
    with engine.begin() as connection:
        connection.execute(text('DELETE FROM validation_reports WHERE post_id=:id'), {'id': post})
    assert client.post(f'/api/projects/1/posts/{post}/approve').status_code == 409
