"""HTTP, генерация, проверки, планировщик и доставка на настоящей PostgreSQL."""

from contextlib import contextmanager
from datetime import timedelta
from io import BytesIO
import json
from pathlib import Path
from time import monotonic, sleep

import httpx
from PIL import Image
import pytest
from sqlalchemy import create_engine, text

from postify.application.ai.gateway import ModelGateway
from postify.bootstrap import open_project_publish_once
from postify.web.app import create_app
from postify.web.dependencies import WebContainer
from postify.web.services import WebApplication
from tests.integration.test_web_component import NOW, _seed, _settings
from tests.unit.web.test_api import ApiClient, AuthStub


pytestmark = pytest.mark.integration


class WorkflowProvider:
    name = "workflow-test"
    model = "workflow-test"
    media_asset_id = 1
    telegram_error = None

    def complete(self, prompt, *, output_schema=None, **kwargs):
        if "post_text" in (output_schema or {}).get("properties", {}):
            return json.dumps({
                "post_text": "Хранение зерна: подготовьте силосы к сезону.",
                "media_asset_id": self.media_asset_id,
                "media_rationale": "Силосы для хранения зерна",
            })
        if "verdict" in (output_schema or {}).get("properties", {}):
            return '{"verdict":"match","detail":"Силосы соответствуют хранению зерна"}'
        return '{"claims":[]}'

    def caption_image(self, path):
        assert path.is_file()
        return "Силосы для хранения зерна"

    def embed(self, value):
        return (1.0,) + (0.0,) * 767


def _wait_operation(client, operation_id, *, expected_status="succeeded"):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        response = client.get(f"/api/projects/1/operations/{operation_id}")
        assert response.status_code == 200, response.text
        operation = response.json()
        if operation["status"] != "running":
            assert operation["status"] == expected_status, operation
            return operation
        sleep(0.02)
    pytest.fail("Операция не завершилась за 10 секунд")


@pytest.fixture
def workflow(migrated_database_url, tmp_path, monkeypatch):
    engine = create_engine(migrated_database_url)
    _seed(engine)
    current_time = [NOW]
    monkeypatch.setattr(WebApplication, "_now", staticmethod(lambda: current_time[0]))
    provider = WorkflowProvider()
    monkeypatch.setattr(
        "postify.web.services.build_model_gateway",
        lambda settings: ModelGateway(provider, provider),
    )
    monkeypatch.setattr(
        "postify.web.media_api.build_model_gateway",
        lambda settings: ModelGateway(provider, provider),
    )
    requests = []

    def telegram(request):
        assert request.url.host == "api.telegram.org"
        assert request.url.path.endswith("/sendPhoto")
        assert b"@workflow" in request.content
        requests.append(request)
        if provider.telegram_error is not None:
            error = provider.telegram_error
            provider.telegram_error = None
            return httpx.Response(error, json={"ok": False, "error_code": error})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 701}})

    @contextmanager
    def open_test_publisher(settings, **kwargs):
        with open_project_publish_once(
            settings, transport=httpx.MockTransport(telegram), **kwargs
        ) as action:
            action.clock = lambda: current_time[0]
            yield action

    monkeypatch.setattr("postify.web.services.open_project_publish_once", open_test_publisher)
    api = WebApplication(_settings(migrated_database_url, tmp_path))
    client = ApiClient(create_app(WebContainer(api=api), auth=AuthStub(owned=(1,))))
    try:
        assert client.put("/api/projects/1/channel", json={"chat_id": "@workflow", "bot_token": "123:test"}).status_code == 200
        yield client, api, engine, provider, current_time, requests
    finally:
        api.close()
        engine.dispose()


def _upload_image(client, provider, *, color="green"):
    image = BytesIO()
    Image.new("RGB", (32, 32), color).save(image, format="JPEG")
    uploaded = client.post("/api/projects/1/media", files={"files": ("silage.jpg", image.getvalue(), "image/jpeg")})
    assert uploaded.status_code == 202, uploaded.text
    result = _wait_operation(client, uploaded.json()["operation_id"])
    assert result["result"]["captioned"] == 1, result
    assets = client.get("/api/projects/1/media").json()["items"]
    asset = next(asset for asset in assets if asset["available"])
    assert asset["caption_status"] == "ready"
    provider.media_asset_id = asset["id"]
    return asset["id"]


def _create_slot(client, *, offset=1):
    created = client.post("/api/projects/1/plan", json={
        "publish_at": (NOW + timedelta(days=offset)).isoformat(),
        "topic": "Хранение зерна",
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_manual_media_selection_records_usage_and_enforces_reuse(workflow):
    client, _, engine, provider, _, _ = workflow
    _upload_image(client, provider)
    slot_id = _create_slot(client)
    generated = client.post(f"/api/projects/1/plan/{slot_id}/generate")
    post_id = _wait_operation(client, generated.json()["operation_id"])["result"]["post_id"]
    replacement = _upload_image(client, provider, color="blue")
    path = f"/api/projects/1/posts/{post_id}"

    changed = client.patch(path, json={"media_asset_id": replacement})
    assert changed.status_code == 200, changed.text
    assert changed.json()["media"]["asset_id"] == replacement
    assert client.patch(path, json={"media_asset_id": replacement}).status_code == 200
    assets = client.get("/api/projects/1/media").json()["items"]
    asset = next(item for item in assets if item["id"] == replacement)
    assert asset["use_count"] == 1
    assert asset["available"] is False
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT count(*) FROM media_usages WHERE asset_id=:asset AND post_id=:post"
        ), {"asset": replacement, "post": post_id}).scalar_one() == 1


@pytest.mark.parametrize("publication_mode", ["review", "auto"])
def test_generation_validation_approval_and_scheduled_delivery(workflow, publication_mode):
    client, api, engine, provider, current_time, requests = workflow
    updated = client.put("/api/projects/1", json={"publication_mode": publication_mode})
    assert updated.status_code == 200, updated.text
    asset_id = _upload_image(client, provider)
    slot_id = _create_slot(client)
    with engine.connect() as connection:
        image_path = Path(connection.execute(text("SELECT file_path FROM media_assets WHERE id=:id"), {"id": asset_id}).scalar_one())

    generated = client.post(f"/api/projects/1/plan/{slot_id}/generate")
    assert generated.status_code == 202, generated.text
    operation = _wait_operation(client, generated.json()["operation_id"])
    post_id = operation["result"]["post_id"]
    post = client.get(f"/api/projects/1/posts/{post_id}").json()
    assert post["validation"]["passed"] is True, post
    assert {layer["layer"] for layer in post["validation"]["layers"]} == {
        "format", "rules", "grounding", "image"
    }
    assert post["media"]["asset_id"] == asset_id
    assert post["status"] == ("needs_review" if publication_mode == "review" else "approved")
    if publication_mode == "review":
        edited = client.patch(f"/api/projects/1/posts/{post_id}", json={"post_text": "Подготовьте силосы к хранению зерна."})
        assert edited.status_code == 200, edited.text
        approved = client.post(f"/api/projects/1/posts/{post_id}/approve")
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"

    assert api.scheduler_tick() == ()
    assert requests == []
    current_time[0] += timedelta(days=1, minutes=1)
    commands = api.scheduler_tick()
    assert [command.kind for command in commands] == ["publish_once"]
    _wait_operation(client, commands[0].operation_run_id)

    published = client.get(f"/api/projects/1/posts/{post_id}").json()
    assert published["status"] == "published"
    assert published["published"]["message_url"] == "https://t.me/workflow/701"
    assert image_path.is_file()
    assert client.get(f"/api/projects/1/media/{asset_id}/file").status_code == 200
    assert api.scheduler_tick() == ()
    assert len(requests) == 1
    deliveries = client.get("/api/projects/1/publications").json()
    assert len(deliveries) == 1
    assert deliveries[0]["attempt_count"] == 1

    assert client.delete("/api/projects/1/channel").status_code == 204
    history = client.get(f"/api/projects/1/posts/{post_id}").json()
    assert history["published"]["message_url"] == "https://t.me/workflow/701"
    removed = client.delete("/api/projects/1")
    assert removed.status_code == 204, removed.text
    assert not image_path.exists()
    assert client.get("/api/projects/1").status_code == 404
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM content_projects WHERE id=2")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM users")).scalar_one() == 2
    assert deliveries[0]["message_id"] == 701


def test_rejection_and_regeneration_keep_the_same_slot_and_post(workflow):
    client, api, engine, provider, current_time, requests = workflow
    first_asset = _upload_image(client, provider)
    slot_id = _create_slot(client)
    generated = client.post(f"/api/projects/1/plan/{slot_id}/generate")
    result = _wait_operation(client, generated.json()["operation_id"])
    post_id = result["result"]["post_id"]
    rejected = client.post(f"/api/projects/1/posts/{post_id}/reject")
    assert rejected.status_code == 200, rejected.text
    second_asset = _upload_image(client, provider, color="red")
    assert second_asset != first_asset

    regenerated = client.post(f"/api/projects/1/posts/{post_id}/regenerate")

    assert regenerated.status_code == 202, regenerated.text
    result = _wait_operation(client, regenerated.json()["operation_id"])
    assert result["result"]["post_id"] == post_id
    post = client.get(f"/api/projects/1/posts/{post_id}").json()
    assert post["slot_id"] == slot_id
    assert post["status"] == "needs_review"
    assert post["media"]["asset_id"] == second_asset
    assert post["validation"]["passed"] is True
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM posts")).scalar_one() == 1
    current_time[0] += timedelta(days=1, minutes=1)
    assert api.scheduler_tick() == ()
    assert requests == []


def test_empty_pool_failure_can_be_retried_after_upload(workflow):
    client, api, engine, provider, current_time, requests = workflow
    slot_id = _create_slot(client)
    generated = client.post(f"/api/projects/1/plan/{slot_id}/generate")
    assert generated.status_code == 202
    result = _wait_operation(client, generated.json()["operation_id"], expected_status="failed")
    assert result["error"]["code"] == "media_pool_empty"
    posts = client.get("/api/projects/1/posts").json()
    assert len(posts) == 1
    assert posts[0]["status"] == "failed"
    post_id = posts[0]["id"]
    _upload_image(client, provider)

    regenerated = client.post(f"/api/projects/1/posts/{post_id}/regenerate")

    assert regenerated.status_code == 202
    _wait_operation(client, regenerated.json()["operation_id"])
    post = client.get(f"/api/projects/1/posts/{post_id}").json()
    assert post["status"] == "needs_review"
    assert post["validation"]["passed"] is True


def test_retryable_delivery_is_retried_through_http_once(workflow):
    client, api, engine, provider, current_time, requests = workflow
    assert client.put("/api/projects/1", json={"publication_mode": "auto"}).status_code == 200
    _upload_image(client, provider)
    slot_id = _create_slot(client)
    generated = client.post(f"/api/projects/1/plan/{slot_id}/generate")
    result = _wait_operation(client, generated.json()["operation_id"])
    post_id = result["result"]["post_id"]
    provider.telegram_error = 429
    current_time[0] += timedelta(days=1, minutes=1)

    command, = api.scheduler_tick()
    _wait_operation(client, command.operation_run_id)
    delivery, = client.get("/api/projects/1/publications").json()
    assert delivery["status"] == "retryable"
    assert delivery["attempt_count"] == 1
    assert client.get(f"/api/projects/1/posts/{post_id}").json()["status"] == "approved"

    retried = client.post(f"/api/projects/1/publications/{delivery['delivery_id']}/retry")

    assert retried.status_code == 202, retried.text
    _wait_operation(client, retried.json()["operation_id"])
    delivery, = client.get("/api/projects/1/publications").json()
    assert delivery["status"] == "published"
    assert delivery["attempt_count"] == 2
    assert [attempt["outcome"] for attempt in delivery["attempts"]] == ["retryable", "published"]
    assert api.scheduler_tick() == ()
    assert len(requests) == 2


@pytest.mark.parametrize("failed_layer", ["rules", "image"])
def test_manual_changes_preserve_all_guardrails_and_block_approval(workflow, monkeypatch, failed_layer):
    client, _, _, provider, _, _ = workflow
    _upload_image(client, provider)
    slot = _create_slot(client)
    generated = client.post(f"/api/projects/1/plan/{slot}/generate")
    post_id = _wait_operation(client, generated.json()["operation_id"])["result"]["post_id"]
    path = f"/api/projects/1/posts/{post_id}"
    original = provider.complete
    if failed_layer == "rules":
        saved = client.put('/api/projects/1/rules', json={"rules": [{
            "text": "Без скидок", "severity": "block", "enabled": True, "origin": "manual",
        }]})
        assert saved.status_code == 200, saved.text
        rule_id = saved.json()[0]['id']
        change = {"post_text": "Скидка на хранение зерна."}
    else:
        replacement = _upload_image(client, provider, color="blue")
        change = {"media_asset_id": replacement}

    def complete(prompt, **kwargs):
        properties = (kwargs.get("output_schema") or {}).get("properties", {})
        if failed_layer == "rules" and "items" in properties:
            return json.dumps({"items": [{"rule_id": rule_id, "passed": False, "evidence": "Упомянута скидка"}]})
        if failed_layer == "image" and "verdict" in properties:
            return json.dumps({"verdict": "mismatch", "detail": "Другой объект"})
        return original(prompt, **kwargs)

    monkeypatch.setattr(provider, "complete", complete)
    changed = client.patch(path, json=change)
    assert changed.status_code == 200, changed.text
    report = changed.json()["validation"]
    assert {layer['layer'] for layer in report['layers']} == {"format", "rules", "grounding", "image"}
    assert report['passed'] is False
    assert next(layer for layer in report['layers'] if layer['layer'] == failed_layer)['passed'] is False
    approval = client.post(path + '/approve')
    assert approval.status_code == 409
    assert ('Упомянута скидка' if failed_layer == 'rules' else 'Другой объект') in approval.text
    assert client.get('/api/projects/1/publications').json() == []


def test_approval_rejects_partial_validation_report(workflow):
    client, _, engine, provider, _, _ = workflow
    _upload_image(client, provider)
    slot = _create_slot(client)
    generated = client.post(f"/api/projects/1/plan/{slot}/generate")
    post_id = _wait_operation(client, generated.json()["operation_id"])["result"]["post_id"]
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM validation_reports WHERE post_id=:id AND layer='image'"), {"id": post_id})
    assert client.post(f'/api/projects/1/posts/{post_id}/approve').status_code == 409


def test_empty_pool_can_generate_text_only(workflow):
    client, api, engine, provider, current_time, requests = workflow
    slot_id = _create_slot(client)
    response = client.post(f"/api/projects/1/plan/{slot_id}/generate")
    failed = _wait_operation(client, response.json()["operation_id"], expected_status="failed")
    assert failed["error"]["message"] == "Упс, не нашли доступное изображение"
    with engine.connect() as connection:
        post_id = connection.execute(text("SELECT post_id FROM content_plan_slots WHERE id=:id"), {"id": slot_id}).scalar_one()
    path = f"/api/projects/1/posts/{post_id}"
    assert client.get(path).json()["generation"]["error_code"] == "media_pool_empty"
    provider.media_asset_id = None
    response = client.post(path + "/regenerate", json={"without_image": True})
    assert response.status_code == 202, response.text
    _wait_operation(client, response.json()["operation_id"])
    post = client.get(path).json()
    assert post["media"] is None
    assert post["status"] == "needs_review"
    assert post["post_text"]
    assert post["validation"]["passed"] is True
    assert post["generation"]["without_image"] is True
    edited = client.patch(path, json={"post_text": "Хранение зерна: проверьте силосы."})
    assert edited.status_code == 200, edited.text
    assert edited.json()["validation"]["passed"] is True
    approved = client.post(path + "/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert not requests


def test_generation_and_manual_edit_share_user_context(workflow, monkeypatch):
    from postify.application.validation.service import ValidationService
    client, _, engine, provider, _, requests = workflow
    drafts = []
    original = ValidationService.validate

    def validate(self, draft):
        drafts.append(draft)
        return original(self, draft)

    monkeypatch.setattr(ValidationService, "validate", validate)
    with engine.begin() as connection:
        connection.execute(text("UPDATE content_projects SET project_prompt='Добавляй анекдоты во все посты' WHERE id=1"))
    slot = _create_slot(client)
    provider.media_asset_id = None
    generated = client.post(f"/api/projects/1/plan/{slot}/generate", json={"without_image": True})
    post_id = _wait_operation(client, generated.json()["operation_id"])["result"]["post_id"]
    edited = client.patch(f"/api/projects/1/posts/{post_id}", json={"post_text": "Хранение зерна: подготовьте силосы."})
    assert edited.status_code == 200, edited.text
    assert len(drafts) == 2
    for draft in drafts:
        assert draft.project_prompt == "Добавляй анекдоты во все посты"
        assert draft.without_image is True
        assert draft.slot.topic == "Хранение зерна"
    assert drafts[0].common_prompt == drafts[1].common_prompt
    assert drafts[0].system_prompt == drafts[1].system_prompt
    assert not requests
