from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from postify.adapters.channels.registry import ChannelProviderRegistry
from postify.adapters.sources.registry import SourceProviderRegistry
from postify.application.projects.bootstrap_project import BootstrapProject
from postify.infrastructure.database.engine import create_engine_from_settings
from postify.infrastructure.repositories.sqlalchemy_projects import SqlAlchemyProjectRepository
from postify.web.app import create_app
from postify.web.dependencies import WebContainer
from postify.web.services import WebApplication
from tests.integration.test_import_component import configured_settings
from tests.unit.web.test_api import ApiClient


pytestmark = pytest.mark.integration


def test_component_bootstrap_uses_real_project_scoped_repositories(
    migrated_database_url: str,
) -> None:
    # Break caught: composition root returns demo data instead of the active project.
    settings = configured_settings(migrated_database_url)
    engine = create_engine_from_settings(settings)
    try:
        projects = SqlAlchemyProjectRepository(sessionmaker(engine))
        BootstrapProject(
            projects,
            SourceProviderRegistry(),
            ChannelProviderRegistry(),
            cipher=None,
            clock=lambda: datetime(2026, 8, 12, 9, tzinfo=UTC),
        ).execute(settings, telegram=None)
        client = ApiClient(create_app(WebContainer(api=WebApplication(settings, None))))

        bootstrap = client.get("/api/v1/bootstrap")

        assert bootstrap.status_code == 200
        assert bootstrap.json()["activeProject"]["id"] == 1
        assert bootstrap.json()["providers"]["channels"][0]["credential"] == {
            "name": "token",
            "label": "Токен бота",
            "input_type": "password",
        }
    finally:
        engine.dispose()


def test_real_bootstrap_drives_channel_secret_create_replace_and_remove(
    migrated_database_url: str,
) -> None:
    # Поломка final review: fixture и production bootstrap расходятся,
    # из-за чего UI не может создать, заменить и удалить token.
    settings = configured_settings(migrated_database_url).model_copy(
        update={
            "postify_secret_key": SecretStr(
                Fernet.generate_key().decode("ascii")
            )
        }
    )
    engine = create_engine_from_settings(settings)
    api = WebApplication(settings, None)
    client = ApiClient(create_app(WebContainer(api=api)))
    first_token = "component-first-secret"
    replacement_token = "component-replacement-secret"
    try:
        bootstrap = client.get("/api/v1/bootstrap")
        provider = bootstrap.json()["providers"]["channels"][0]
        assert provider["credential"] == {
            "name": "token",
            "label": "Токен бота",
            "input_type": "password",
        }
        assert "secret" not in provider

        created = client.post(
            "/api/v1/projects/1/channels",
            json={
                "provider": provider["code"],
                "name": "Component lifecycle",
                "enabled": True,
                "configuration": {"chat_id": "-100-component"},
                provider["credential"]["name"]: first_token,
            },
        )
        assert created.status_code == 201
        channel_id = created.json()["id"]
        assert created.json()["secretConfigured"] is True

        replaced = client.put(
            f"/api/v1/projects/1/channels/{channel_id}",
            json={
                "provider": provider["code"],
                "name": "Component lifecycle",
                "enabled": True,
                "configuration": {"chat_id": "-100-component"},
                provider["credential"]["name"]: replacement_token,
            },
        )
        listed = client.get("/api/v1/projects/1/channels")
        removed = client.post(
            f"/api/v1/projects/1/channels/{channel_id}/secret/remove"
        )
        listed_after = client.get("/api/v1/projects/1/channels")

        assert replaced.status_code == 200
        assert replaced.json()["secretConfigured"] is True
        assert listed.json()["items"][0]["secretConfigured"] is True
        assert removed.status_code == 200
        assert removed.json()["secretConfigured"] is False
        assert listed_after.json()["items"][0]["secretConfigured"] is False
        outbound = json.dumps(
            [
                bootstrap.json(),
                created.json(),
                replaced.json(),
                listed.json(),
                removed.json(),
                listed_after.json(),
            ]
        )
        assert first_token not in outbound
        assert replacement_token not in outbound

        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT encrypted_secret FROM channel_connections "
                    "WHERE project_id=1 AND id=:id"
                ),
                {"id": channel_id},
            ).scalar_one_or_none() is None
    finally:
        api.close()
        engine.dispose()


def test_component_media_uses_persisted_mime(
    migrated_database_url: str, tmp_path: Path
) -> None:
    # Поломка review: every stored PNG/WebP отдаётся как image/jpeg.
    settings = configured_settings(migrated_database_url).model_copy(
        update={"content_media_dir": tmp_path}
    )
    engine = create_engine_from_settings(settings)
    media = tmp_path / "component.webp"
    media.write_bytes(b"RIFF-component-webp")
    try:
        client = ApiClient(create_app(WebContainer(api=WebApplication(settings, None))))
        now = datetime(2026, 8, 12, 9, tzinfo=UTC)
        with engine.begin() as connection:
            candidate_id = connection.execute(
                text(
                    """INSERT INTO candidates
                    (project_id,source_name,source_id,title,url,discovered_at,raw_payload)
                    VALUES (1,'source','component-media','Media',
                            'https://example.test/media',:now,'{}') RETURNING id"""
                ),
                {"now": now},
            ).scalar_one()
            attempt_id = connection.execute(
                text(
                    """INSERT INTO content_attempts
                    (project_id,candidate_id,attempt_no,status,source_url,started_at)
                    VALUES (1,:candidate,1,'packaged',
                            'https://example.test/media',:now) RETURNING id"""
                ),
                {"candidate": candidate_id, "now": now},
            ).scalar_one()
            package_id = connection.execute(
                text(
                    """INSERT INTO content_packages
                    (project_id,attempt_id,source_url,context,analysis,post_text,
                     media_path,media_mime,media_source_type,media_source_url,
                     status,generation_snapshot,created_at,updated_at)
                    VALUES (1,:attempt,'https://example.test/media','Context','Анализ',
                            'Post',:path,'image/webp','og','https://cdn.test/a.webp',
                            'approved','{}',:now,:now) RETURNING id"""
                ),
                {"attempt": attempt_id, "path": str(media), "now": now},
            ).scalar_one()
            future = datetime.now(UTC) + timedelta(days=1)
            connection.execute(text("""
                INSERT INTO content_formats
                    (id,project_id,name,kind,instructions,enabled,created_at,updated_at)
                VALUES (401,1,'Тестовый формат','text','Короткий пост',true,:now,:now)
            """), {"now": now})
            connection.execute(text("""
                INSERT INTO channel_connections
                    (id,project_id,provider,name,enabled,configuration,connection_status,created_at,updated_at)
                VALUES (401,1,'telegram','Тестовый канал',true,'{"chat_id":"-100-review"}',
                        'configured',:now,:now)
            """), {"now": now})
            connection.execute(text("""
                INSERT INTO publication_routes
                    (id,project_id,format_id,channel_id,enabled,created_at,updated_at)
                VALUES (401,1,401,401,true,:now,:now)
            """), {"now": now})
            connection.execute(text("""
                UPDATE content_packages SET scheduled_at=:scheduled,route_id=401
                WHERE project_id=1 AND id=:id
            """), {"scheduled": future, "id": package_id})

        response = client.get(f"/api/v1/projects/1/media/packages/{package_id}")

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "image/webp"
        assert response.content == b"RIFF-component-webp"
    finally:
        engine.dispose()


def test_component_queue_returns_planned_package_in_project_timezone(
    migrated_database_url: str,
) -> None:
    settings = configured_settings(migrated_database_url).model_copy(
        update={"postify_timezone": "Europe/Moscow"}
    )
    engine = create_engine_from_settings(settings)
    api = WebApplication(settings, None)
    client = ApiClient(create_app(WebContainer(api=api)))
    now = datetime.now(UTC)
    scheduled_at = now + timedelta(hours=1)
    try:
        with engine.begin() as connection:
            candidate_id = connection.execute(text("""
                INSERT INTO candidates
                    (project_id,source_name,source_id,title,url,discovered_at,raw_payload)
                VALUES (1,'source','queue-component','Queue package',
                        'https://example.test/queue',:now,'{}'::jsonb)
                RETURNING id
            """), {"now": now}).scalar_one()
            attempt_id = connection.execute(text("""
                INSERT INTO content_attempts
                    (project_id,candidate_id,attempt_no,status,source_url,started_at)
                VALUES (1,:candidate,1,'packaged','https://example.test/queue',:now)
                RETURNING id
            """), {"candidate": candidate_id, "now": now}).scalar_one()
            package_id = connection.execute(text("""
                INSERT INTO content_packages
                    (project_id,attempt_id,source_url,context,analysis,post_text,status,
                     generation_snapshot,created_at,updated_at)
                VALUES (1,:attempt,'https://example.test/queue','Context','Analysis',
                        'Planned post','awaiting_review','{}'::jsonb,:now,:now)
                RETURNING id
            """), {"attempt": attempt_id, "now": now}).scalar_one()
            connection.execute(text("""
                INSERT INTO channel_connections
                    (id,project_id,provider,name,enabled,configuration,connection_status,created_at,updated_at)
                VALUES (501,1,'telegram','Queue channel',true,'{"chat_id":"-100-queue"}',
                        'configured',:now,:now)
            """), {"now": now})
            connection.execute(text("""
                INSERT INTO publication_routes
                    (id,project_id,format_id,channel_id,enabled,created_at,updated_at)
                VALUES (501,1,1,501,true,:now,:now)
            """), {"now": now})
            connection.execute(text("""
                UPDATE content_packages
                SET scheduled_at=:scheduled_at, route_id=501
                WHERE project_id=1 AND id=:package_id
            """), {"scheduled_at": scheduled_at, "package_id": package_id})

        response = client.get("/api/v1/projects/1/queue")

        assert response.status_code == 200, response.text
        item = next(item for item in response.json()["items"] if item["package_id"] == package_id)
        assert item["status"] == "awaiting_review"
        assert datetime.fromisoformat(item["scheduled_at"]) == scheduled_at
        assert item["slot_time"] == scheduled_at.astimezone(ZoneInfo("Europe/Moscow")).strftime("%H:%M")
    finally:
        api.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("action", "expected_status"),
    [("approve", "approved"), ("reject", "rejected")],
)
def test_component_review_returns_the_committed_package_status(
    migrated_database_url: str,
    tmp_path: Path,
    action: str,
    expected_status: str,
) -> None:
    # Break caught: the transition commits, but reconstructing the domain package
    # raises afterwards and the real API reports a false 422 to the browser.
    settings = configured_settings(migrated_database_url).model_copy(
        update={"content_media_dir": tmp_path}
    )
    engine = create_engine_from_settings(settings)
    api = WebApplication(settings, None)
    client = ApiClient(create_app(WebContainer(api=api)))
    media = tmp_path / f"review-{action}.png"
    media.write_bytes(b"review-media")
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    try:
        with engine.begin() as connection:
            candidate_id = connection.execute(
                text(
                    """INSERT INTO candidates
                    (project_id,source_name,source_id,title,url,discovered_at,raw_payload)
                    VALUES (1,'source',:source_id,'Review package',
                            'https://example.test/review',:now,'{}'::jsonb)
                    RETURNING id"""
                ),
                {"source_id": f"component-review-{action}", "now": now},
            ).scalar_one()
            attempt_id = connection.execute(
                text(
                    """INSERT INTO content_attempts
                    (project_id,candidate_id,attempt_no,status,source_url,started_at)
                    VALUES (1,:candidate,1,'packaged',
                            'https://example.test/review',:now) RETURNING id"""
                ),
                {"candidate": candidate_id, "now": now},
            ).scalar_one()
            package_id = connection.execute(
                text(
                    """INSERT INTO content_packages
                    (project_id,attempt_id,source_url,context,analysis,post_text,
                     media_path,media_mime,media_source_type,media_source_url,
                     status,generation_snapshot,created_at,updated_at)
                    VALUES (1,:attempt,'https://example.test/review','Context','Analysis',
                            'Generated post without source link',:path,'image/png','og',
                            'https://cdn.test/review.png','awaiting_review','{}'::jsonb,
                            :now,:now) RETURNING id"""
                ),
                {"attempt": attempt_id, "path": str(media), "now": now},
            ).scalar_one()

        with engine.begin() as connection:
            future = datetime.now(UTC) + timedelta(days=1)
            connection.execute(text("""INSERT INTO content_formats
                (id,project_id,name,kind,instructions,enabled,created_at,updated_at)
                VALUES (402,1,'Плановый формат','text','Короткий пост',true,:now,:now)"""), {"now": now})
            connection.execute(text("""INSERT INTO channel_connections
                (id,project_id,provider,name,enabled,configuration,connection_status,created_at,updated_at)
                VALUES (402,1,'telegram','Плановый канал',true,'{"chat_id":"-100-plan"}','configured',:now,:now)"""), {"now": now})
            connection.execute(text("""INSERT INTO publication_routes
                (id,project_id,format_id,channel_id,enabled,created_at,updated_at)
                VALUES (402,1,402,402,true,:now,:now)"""), {"now": now})
            connection.execute(text("UPDATE content_packages SET scheduled_at=:at,route_id=402 WHERE id=:id"), {"at": future, "id": package_id})

        response = client.post(
            f"/api/v1/projects/1/packages/{package_id}/{action}"
        )

        assert response.status_code == 200
        assert response.json()["status"] == expected_status
    finally:
        api.close()
        engine.dispose()


def test_component_lists_persisted_packages_without_status_filter(
    migrated_database_url: str,
) -> None:
    # Break caught: PostgreSQL cannot infer the type of a None status bind and returns 503.
    settings = configured_settings(migrated_database_url)
    engine = create_engine_from_settings(settings)
    try:
        client = ApiClient(create_app(WebContainer(api=WebApplication(settings, None))))
        now = datetime(2026, 8, 12, 9, tzinfo=UTC)
        with engine.begin() as connection:
            candidate_id = connection.execute(
                text(
                    """INSERT INTO candidates
                    (project_id,source_name,source_id,title,url,discovered_at,raw_payload)
                    VALUES (1,'source','component-package','Пакет компонента',
                            'https://example.test/package',:now,'{}'::jsonb)
                    RETURNING id"""
                ),
                {"now": now},
            ).scalar_one()
            attempt_id = connection.execute(
                text(
                    """INSERT INTO content_attempts
                    (project_id,candidate_id,attempt_no,status,source_url,started_at)
                    VALUES (1,:candidate,1,'packaged',
                            'https://example.test/package',:now) RETURNING id"""
                ),
                {"candidate": candidate_id, "now": now},
            ).scalar_one()
            connection.execute(
                text(
                    """INSERT INTO content_packages
                    (project_id,attempt_id,source_url,context,analysis,post_text,
                     status,generation_snapshot,created_at,updated_at)
                    VALUES (1,:attempt,'https://example.test/package','Контекст',
                            'Анализ','Текст пакета','awaiting_review',
                            '{}'::jsonb,:now,:now)"""
                ),
                {"attempt": attempt_id, "now": now},
            )

        response = client.get("/api/v1/projects/1/packages")

        assert response.status_code == 200
        assert response.json()["items"][0]["post_text"] == "Текст пакета"
    finally:
        engine.dispose()
