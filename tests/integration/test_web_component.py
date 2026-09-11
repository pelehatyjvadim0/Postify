"""Компонентный тест веб-слоя на настоящей PostgreSQL.

Поднимается весь стек кроме входа: HTTP, фасад, действия и репозитории. Вход
подменён, потому что он проверяется своим треком; здесь важно, что маршруты
доходят до базы и возвращают контракт.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import json

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from postify.config import Settings
from postify.domain.projects.models import ProjectConfiguration
from postify.web.app import create_app
from postify.web.dependencies import WebContainer
from postify.web.services import WebApplication
from tests.unit.web.test_api import OWNER, ApiClient, AuthStub


pytestmark = pytest.mark.integration


NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
OWN_PROJECT = 1
FOREIGN_PROJECT = 2
CONFIGURATION = json.dumps(
    asdict(
        ProjectConfiguration(media_max_bytes=10_000_000, analysis_timeout_seconds=60)
    )
)


def _settings(database_url: str, tmp_path) -> Settings:
    return Settings(
        database_url=database_url,
        content_media_dir=tmp_path,
        postify_secret_key=SecretStr(Fernet.generate_key().decode("ascii")),
    )


def _seed(engine) -> None:
    """Два пользователя с проектом у каждого: чужой проект должен быть невидим."""
    with engine.begin() as connection:
        for user_id, telegram in ((OWNER.id, "101"), (OWNER.id + 1, "202")):
            connection.execute(
                text(
                    "INSERT INTO users(id,telegram_user_id,telegram_username,"
                    "display_name,created_at,is_active)"
                    " VALUES (:id,:telegram,:username,:name,:now,true)"
                ),
                {
                    "id": user_id,
                    "telegram": telegram,
                    "username": f"user_{telegram}",
                    "name": f"Пользователь {telegram}",
                    "now": NOW,
                },
            )
        for project_id, owner_id, name in (
            (OWN_PROJECT, OWNER.id, "Агротех"),
            (FOREIGN_PROJECT, OWNER.id + 1, "Чужой"),
        ):
            connection.execute(
                text(
                    "INSERT INTO content_projects(id,name,project_prompt,language,audience,"
                    "timezone,configuration,created_at,updated_at,owner_id)"
                    " VALUES (:id,:name,:prompt,'ru','Фермеры','Europe/Moscow',"
                    "CAST(:configuration AS jsonb),:now,:now,:owner)"
                ),
                {
                    "id": project_id,
                    "name": name,
                    "prompt": name,
                    "configuration": CONFIGURATION,
                    "now": NOW,
                    "owner": owner_id,
                },
            )
        # Строки вставлены с явными id, поэтому последовательность надо
        # подвинуть: иначе следующий INSERT возьмёт занятый id.
        for table in ("users", "content_projects"):
            connection.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table}','id'),"
                    f" (SELECT max(id) FROM {table}))"
                )
            )


def _seed_post(engine, *, post_id: int, scheduled_at: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO posts(id,project_id,post_text,status,scheduled_at,"
                "generation,created_at,updated_at)"
                " VALUES (:id,:project,:post_text,'needs_review',:scheduled_at,"
                "CAST(:generation AS jsonb),:now,:now)"
            ),
            {
                "id": post_id,
                "project": OWN_PROJECT,
                "post_text": "Первая версия поста",
                "scheduled_at": scheduled_at,
                "generation": json.dumps({"provider": "codex"}),
                "now": NOW,
            },
        )
        connection.execute(
            text(
                "INSERT INTO content_plan_slots(id,project_id,publish_at,generate_at,"
                "topic,status,post_id,created_at,updated_at)"
                " VALUES (:id,:project,:publish_at,:generate_at,'Тестовая тема',"
                "'needs_review',:post,:now,:now)"
            ),
            {
                "id": post_id,
                "project": OWN_PROJECT,
                "publish_at": scheduled_at,
                "generate_at": scheduled_at - timedelta(days=1),
                "post": post_id,
                "now": NOW,
            },
        )


@pytest.fixture
def component(migrated_database_url: str, tmp_path):
    engine = create_engine(migrated_database_url)
    _seed(engine)
    api = WebApplication(_settings(migrated_database_url, tmp_path))
    app = create_app(
        WebContainer(api=api), auth=AuthStub(owned=(OWN_PROJECT,))
    )
    try:
        yield ApiClient(app), engine
    finally:
        api.close()
        engine.dispose()


def test_project_is_read_and_edited_through_the_real_repository(component) -> None:
    client, _ = component

    read = client.get(f"/api/projects/{OWN_PROJECT}")
    updated = client.put(
        f"/api/projects/{OWN_PROJECT}",
        json={"name": "Агротех+", "tone": "Дружелюбный"},
    )
    reread = client.get(f"/api/projects/{OWN_PROJECT}")

    assert read.status_code == 200
    assert read.json()["channel"] == {
        "configured": False,
        "chat_id": "",
        "status": "unconfigured",
        "checked_at": None,
    }
    assert updated.status_code == 200
    assert reread.json()["name"] == "Агротех+"
    assert reread.json()["tone"] == "Дружелюбный"


def test_rubrics_survive_the_round_trip(component) -> None:
    client, _ = component

    created = client.post(
        f"/api/projects/{OWN_PROJECT}/rubrics",
        json={"name": "Кейс", "instructions": "Разбор задачи"},
    )
    rubric_id = created.json()["id"]
    disabled = client.put(
        f"/api/projects/{OWN_PROJECT}/rubrics/{rubric_id}", json={"enabled": False}
    )
    listed = client.get(f"/api/projects/{OWN_PROJECT}/rubrics")
    deleted = client.delete(f"/api/projects/{OWN_PROJECT}/rubrics/{rubric_id}")
    empty = client.get(f"/api/projects/{OWN_PROJECT}/rubrics")

    assert created.status_code == 201
    assert disabled.json()["enabled"] is False
    assert listed.json()[0]["instructions"] == "Разбор задачи"
    assert deleted.status_code == 204
    assert empty.json() == []


def test_channel_token_is_stored_encrypted_and_never_returned(component) -> None:
    client, engine = component

    saved = client.put(
        f"/api/projects/{OWN_PROJECT}/channel",
        json={"bot_token": "123:super-secret", "chat_id": "@agrotech"},
    )
    with engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT encrypted_secret FROM channel_connections"
                " WHERE project_id=:project"
            ),
            {"project": OWN_PROJECT},
        ).scalar_one()
    removed = client.delete(f"/api/projects/{OWN_PROJECT}/channel")
    after = client.get(f"/api/projects/{OWN_PROJECT}")

    assert saved.status_code == 200
    assert saved.json()["configured"] is True
    assert "super-secret" not in saved.text
    assert "super-secret" not in stored
    assert removed.status_code == 204
    assert after.json()["channel"]["configured"] is False


def test_post_is_planned_and_approved_through_http(component) -> None:
    client, engine = component
    scheduled_at = datetime.now(UTC) + timedelta(days=1)
    _seed_post(engine, post_id=77, scheduled_at=scheduled_at)
    client.put(
        f"/api/projects/{OWN_PROJECT}/channel",
        json={"bot_token": "123:secret", "chat_id": "@agrotech"},
    )

    listed = client.get(f"/api/projects/{OWN_PROJECT}/posts?status=needs_review")
    edited = client.patch(
        f"/api/projects/{OWN_PROJECT}/posts/77", json={"post_text": "Правка редактора"}
    )
    approved = client.post(f"/api/projects/{OWN_PROJECT}/posts/77/approve")

    assert [item["id"] for item in listed.json()] == [77]
    # Время отдаётся в таймзоне проекта, а не в UTC.
    assert listed.json()[0]["publish_at"].endswith("+03:00")
    assert edited.json()["post_text"] == "Правка редактора"
    assert approved.json()["status"] == "approved"
    assert [entry["status"] for entry in approved.json()["history"]] == [
        "needs_review",
        "approved",
    ]


def test_expired_plan_is_a_conflict_not_a_crash(component) -> None:
    client, engine = component
    _seed_post(engine, post_id=78, scheduled_at=NOW)
    client.put(
        f"/api/projects/{OWN_PROJECT}/channel",
        json={"bot_token": "123:secret", "chat_id": "@agrotech"},
    )

    response = client.post(f"/api/projects/{OWN_PROJECT}/posts/78/approve")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_plan_expired"
    assert response.json()["error"]["message"]


def test_journals_are_empty_but_readable(component) -> None:
    client, _ = component

    operations = client.get(f"/api/projects/{OWN_PROJECT}/operations")
    publications = client.get(f"/api/projects/{OWN_PROJECT}/publications")

    assert operations.json() == []
    assert publications.json() == []


def test_foreign_project_is_invisible_on_real_data(component) -> None:
    """Чужой проект существует в базе, но пользователю отвечают 404."""
    client, _ = component

    read = client.get(f"/api/projects/{FOREIGN_PROJECT}")
    posts = client.get(f"/api/projects/{FOREIGN_PROJECT}/posts")
    edited = client.put(
        f"/api/projects/{FOREIGN_PROJECT}", json={"name": "Захвачено"}
    )

    for response in (read, posts, edited):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert "Чужой" not in response.text


def test_project_is_created_for_the_current_owner(component) -> None:
    """Проект заводится на вошедшего: ``content_projects.owner_id`` NOT NULL."""
    client, engine = component

    created = client.post(
        "/api/projects", json={"name": "Новый", "timezone": "Europe/Moscow"}
    )

    assert created.status_code == 201
    with engine.connect() as connection:
        owner = connection.execute(
            text("SELECT owner_id FROM content_projects WHERE id=:id"),
            {"id": created.json()["id"]},
        ).scalar_one()
    assert owner == OWNER.id
    listed = client.get("/api/projects")
    assert {item["id"] for item in listed.json()} == {
        OWN_PROJECT,
        created.json()["id"],
    }
