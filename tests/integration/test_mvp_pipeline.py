"""Сквозной тест приложения с реальной БД и подменой только внешнего HTTP."""

from datetime import UTC, datetime, timedelta
import json

import httpx
import pytest
from pydantic import SecretStr

from postify.adapters.sources.telegram_group import TelegramMessage
from postify.bootstrap import open_project_run_once
from postify.config import Settings
from postify.web.app import create_app
from postify.web.dependencies import WebContainer
from postify.web.services import WebApplication
from tests.unit.web.test_api import ApiClient


pytestmark = pytest.mark.integration


def test_arabic_import_gemini_saved_plan_and_moderation(migrated_database_url, tmp_path):
    settings = Settings(
        database_url=migrated_database_url,
        content_analyzer="gemini",
        content_model="gemini-3.8-flash",
        content_media_dir=tmp_path,
        gemini_api_key=SecretStr("test-only-key"),
    )
    api = WebApplication(settings, None)
    client = ApiClient(create_app(WebContainer(api=api)))
    assert client.get("/api/v1/projects/1/settings").json()["project"]["configuration"]["analysis_model"] == "gemini-3.8-flash"
    original = "افتتحت المكتبة يوم 12 مايو وفيها 300 كتاب."
    translated = "Библиотека открылась 12 мая. В ней 300 книг."
    requests = []

    def gemini(request):
        requests.append(request)
        assert request.url.host == "generativelanguage.googleapis.com"
        material = json.loads(json.loads(request.content)["input"])["materials"][0]
        assert material["text"] == original
        return httpx.Response(200, json={"status": "completed", "steps": [{
            "type": "model_output", "content": [{"type": "text", "text": json.dumps({
                "topics": [{"attempt_id": material["attempt_id"], "analysis": "Сохранены факты.", "post_text": translated}]
            }, ensure_ascii=False)}]
        }]})

    try:
        source = client.post("/api/v1/projects/1/sources", json={
            "provider": "telegram_group", "name": "Тестовая группа", "enabled": True,
            "configuration": {"group_id": "test-group"}, "schedule": "0 0 * * *",
        })
        assert source.status_code == 201, source.text
        now = datetime.now(UTC)
        reader = lambda group: [TelegramMessage(17, original, now)]
        with open_project_run_once(settings, project_id=1, telegram_reader=reader,
                                   transport=httpx.MockTransport(gemini)) as action:
            first = action.execute()
        assert first.import_result.created == 1
        assert first.content_result.packages_created == 1
        with open_project_run_once(settings, project_id=1, telegram_reader=reader,
                                   transport=httpx.MockTransport(gemini)) as action:
            second = action.execute()
        assert second.import_result.duplicates == 1
        assert second.content_result.packages_created == 0
        assert len(requests) == 1
        packages = client.get("/api/v1/projects/1/packages").json()["items"]
        assert len(packages) == 1
        package_id = packages[0]["package_id"]
        path = f"/api/v1/projects/1/packages/{package_id}"
        detail = client.get(path).json()
        assert detail["post_text"] == translated
        assert detail["original_text"] == original
        assert detail["status"] == "awaiting_review"
        assert detail["scheduled_at"] is None
        assert client.post(f"{path}/approve").status_code == 409

        channel = client.post("/api/v1/projects/1/channels", json={
            "provider": "telegram", "name": "Тестовый канал", "enabled": True,
            "configuration": {"chat_id": "-100123456"},
        })
        assert channel.status_code == 201, channel.text
        route = client.post("/api/v1/projects/1/routes", json={
            "format_id": 1, "channel_id": channel.json()["id"], "enabled": True,
        })
        assert route.status_code == 201, route.text
        planned_at = (now + timedelta(hours=1)).isoformat()
        saved = client.request("PATCH", f"{path}/plan", json={
            "scheduled_at": planned_at, "route_id": route.json()["id"],
        })
        assert saved.status_code == 200, saved.text
        reloaded = client.get(path).json()
        assert datetime.fromisoformat(reloaded["scheduled_at"]) == datetime.fromisoformat(planned_at)
        assert reloaded["route_id"] == route.json()["id"]
        assert client.post(f"{path}/approve").status_code == 200
        assert client.get(path).json()["status"] == "approved"
        assert client.post(f"{path}/reject").status_code == 409
        assert client.put("/api/v1/projects/1/settings/configuration", json={"delivery_lateness_seconds": 60}).status_code == 200
        assert client.get("/api/v1/projects/1/settings").json()["project"]["configuration"]["delivery_lateness_seconds"] == 60
        assert client.put("/api/v1/projects/1/settings/configuration", json={"delivery_lateness_seconds": None}).status_code == 200
        assert client.get("/api/v1/projects/1/settings").json()["project"]["configuration"]["delivery_lateness_seconds"] is None
    finally:
        api.close()


def test_default_run_can_start_after_migrations_without_opening_ui(migrated_database_url, tmp_path):
    from postify.bootstrap import open_run_once
    settings = Settings(database_url=migrated_database_url, content_media_dir=tmp_path,
                        content_analyzer="gemini", content_model="gemini-3.8-flash")
    def no_external_request(request):
        pytest.fail("Fresh project has no enabled source")
    with open_run_once(settings, transport=httpx.MockTransport(no_external_request)) as action:
        result = action.execute()
    assert result.import_result.received == 0
    assert result.content_result.packages_created == 0
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from postify.infrastructure.repositories.sqlalchemy_projects import SqlAlchemyProjectRepository
    engine = create_engine(migrated_database_url)
    try:
        graph = SqlAlchemyProjectRepository(sessionmaker(engine)).runtime_graph(1)
        assert graph.project.id == 1
        assert graph.formats
        assert graph.sources == ()
    finally:
        engine.dispose()
