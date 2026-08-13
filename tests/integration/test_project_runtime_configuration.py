from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
from subprocess import CompletedProcess

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from postify.web.app import create_app
from postify.web.dependencies import WebContainer
from postify.web.services import WebApplication
from tests.integration.test_import_component import configured_settings
from tests.unit.web.test_api import ApiClient


pytestmark = pytest.mark.integration


def test_api_mutation_changes_next_real_project_run(
    migrated_database_url: str, tmp_path: Path
) -> None:
    # Поломка: HTTP сохраняет graph, но web run продолжает читать process-startup env.
    from postify.bootstrap import open_project_run_once

    settings = configured_settings(migrated_database_url).model_copy(
        update={
            "content_media_dir": tmp_path,
            "postify_secret_key": SecretStr(Fernet.generate_key().decode("ascii")),
        }
    )
    api = WebApplication(settings, None)
    client = ApiClient(create_app(WebContainer(api=api)))
    try:
        main = client.put(
            "/api/v1/projects/1/settings/main",
            json={
                "name": "Runtime project",
                "topic": "Сохранённая тема",
                "language": "uk",
                "audience": "Редакторы runtime",
                "timezone": "UTC",
            },
        )
        configuration = client.put(
            "/api/v1/projects/1/settings/configuration",
            json={
                "daily_analysis_limit": 1,
                "daily_package_limit": 1,
                "priority_freshness_days": 5,
                "fresh_share_percent": 100,
                "reserve_share_percent": 0,
                "review_required": False,
                "article_max_bytes": 50_000,
                "media_max_bytes": 10_000,
                "analysis_timeout_seconds": 7,
            },
        )
        first_source = client.put(
            "/api/v1/projects/1/sources/1",
            json={
                "provider": "hn_algolia",
                "name": "Runtime A",
                "enabled": True,
                "configuration": {
                    "url": "https://runtime-a.example/api",
                    "query": "persisted-a",
                    "tags": "story",
                    "hits": 3,
                },
                "schedule": "0 8 * * *",
            },
        )
        second_source = client.post(
            "/api/v1/projects/1/sources",
            json={
                "provider": "hn_algolia",
                "name": "Runtime B",
                "enabled": True,
                "configuration": {
                    "url": "https://runtime-b.example/api",
                    "query": "persisted-b",
                    "tags": "show_hn",
                    "hits": 4,
                },
                "schedule": "15 8 * * *",
            },
        )
        channel = client.post(
            "/api/v1/projects/1/channels",
            json={
                "provider": "telegram",
                "name": "Runtime channel",
                "enabled": True,
                "configuration": {"chat_id": "-100-runtime"},
                "token": "runtime-secret-token",
            },
        )
        assert channel.status_code == 201
        channel_id = channel.json()["id"]
        route = client.post(
            "/api/v1/projects/1/routes",
            json={
                "format_id": 1,
                "channel_id": channel_id,
                "cta_id": 1,
                "enabled": True,
                "schedule": {
                    "autopublish": True,
                    "slots": ["09:00", "14:00", "19:00"],
                },
            },
        )
        assert [
            item.status_code
            for item in (
                main,
                configuration,
                first_source,
                second_source,
                channel,
                route,
            )
        ] == [
            200,
            200,
            200,
            201,
            201,
            201,
        ]
        route_id = route.json()["id"]

        source_requests: list[tuple[str, str, str]] = []
        now = datetime.now(UTC)

        def transport_handler(request: httpx.Request) -> httpx.Response:
            if request.url.host in {"runtime-a.example", "runtime-b.example"}:
                source_requests.append(
                    (
                        request.url.host,
                        request.url.params["query"],
                        request.url.params["hitsPerPage"],
                    )
                )
                marker = "a" if request.url.host == "runtime-a.example" else "b"
                return httpx.Response(
                    200,
                    json={
                        "hits": [
                            {
                                "objectID": f"runtime-{marker}",
                                "title": f"Runtime material {marker}",
                                "url": f"https://article.example/{marker}",
                                "created_at_i": int(now.timestamp()),
                            }
                        ]
                    },
                )
            if request.url.host == "article.example":
                marker = request.url.path.rsplit("/", 1)[-1]
                body = (
                    f"<html><head><title>Article {marker}</title>"
                    f'<meta property="og:image" content="https://media.example/{marker}.png">'
                    "</head><article>"
                    + ("Runtime article body with practical details. " * 12)
                    + "</article></html>"
                )
                return httpx.Response(200, text=body, headers={"content-type": "text/html"})
            if request.url.host == "media.example":
                return httpx.Response(
                    200,
                    content=b"runtime-png",
                    headers={"content-type": "image/png"},
                )
            raise AssertionError(str(request.url))

        prompts: list[str] = []
        timeouts: list[float] = []

        def analyzer_runner(argv, **kwargs):
            prompts.append(kwargs["input"])
            timeouts.append(kwargs["timeout"])
            attempt_ids = tuple(
                int(value) for value in re.findall(r"Попытка (\d+)\.", kwargs["input"])
            )
            output = Path(argv[argv.index("--output-last-message") + 1])
            output.write_text(
                json.dumps(
                    {
                        "topics": [
                            {
                                "attempt_id": attempt_id,
                                "analysis": "Runtime анализ",
                                "usefulness": 90,
                                "selected": index == 0,
                                "post_text": "Runtime post" if index == 0 else None,
                                "media_query": "runtime" if index == 0 else None,
                            }
                            for index, attempt_id in enumerate(attempt_ids)
                        ]
                    }
                ),
                encoding="utf-8",
            )
            return CompletedProcess(argv, 0, "", "")

        with open_project_run_once(
            settings,
            project_id=1,
            transport=httpx.MockTransport(transport_handler),
            analyzer_runner=analyzer_runner,
        ) as action:
            result = action.execute()

        assert result.import_result.created == 2
        if result.content_result.packages_created != 1:
            engine = create_engine(migrated_database_url)
            try:
                with engine.connect() as connection:
                    attempts = connection.execute(
                        text(
                            "SELECT status,failure_code FROM content_attempts "
                            "WHERE project_id=1 ORDER BY id"
                        )
                    ).all()
                    packages = connection.execute(
                        text(
                            "SELECT status FROM content_packages "
                            "WHERE project_id=1 ORDER BY id"
                        )
                    ).all()
            finally:
                engine.dispose()
            pytest.fail(
                f"content={result.content_result!r}; attempts={attempts!r}; "
                f"packages={packages!r}; prompts={len(prompts)}; "
                f"files={[item.name for item in tmp_path.iterdir()]!r}"
            )
        assert source_requests == [
            ("runtime-a.example", "persisted-a", "3"),
            ("runtime-b.example", "persisted-b", "4"),
        ]
        assert timeouts == [7]
        assert "Тема проекта: Сохранённая тема" in prompts[0]
        assert "Язык: uk" in prompts[0]
        assert "Аудитория: Редакторы runtime" in prompts[0]
        assert "Формат: Короткий хук" in prompts[0]
        assert "CTA: Открыть источник" in prompts[0]

        publish_requests: list[tuple[str, bytes]] = []

        def publish_handler(request: httpx.Request) -> httpx.Response:
            publish_requests.append((str(request.url), request.read()))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 73}})

        from postify.bootstrap import open_project_publish_once

        with open_project_publish_once(
            settings,
            project_id=1,
            transport=httpx.MockTransport(publish_handler),
        ) as publish_action:
            publish_result = publish_action.execute()

        assert publish_result.outcome == "published"
        assert publish_requests[0][0] == (
            "https://api.telegram.org/botruntime-secret-token/sendPhoto"
        )
        assert b'-100-runtime' in publish_requests[0][1]

        engine = create_engine(migrated_database_url)
        try:
            with engine.connect() as connection:
                stored = connection.execute(
                    text(
                        """SELECT status,media_mime,generation_snapshot
                        FROM content_packages WHERE project_id=1"""
                    )
                ).mappings().one()
                delivery = connection.execute(
                    text(
                        """SELECT route_id,channel_id,channel_snapshot,message_id,status
                        FROM deliveries WHERE project_id=1"""
                    )
                ).mappings().one()
                usage = connection.execute(
                    text(
                        "SELECT analyses_started,packages_created FROM content_daily_usage WHERE project_id=1"
                    )
                ).one()
            assert stored.status == "published"
            assert stored.media_mime == "image/png"
            assert stored.generation_snapshot["topic"] == "Сохранённая тема"
            assert stored.generation_snapshot["format"]["id"] == 1
            assert stored.generation_snapshot["cta"]["id"] == 1
            assert delivery.route_id == route_id
            assert delivery.channel_id == channel_id
            assert delivery.channel_snapshot == {
                "id": channel_id,
                "name": "Runtime channel",
                "provider": "telegram",
                "configuration": {"chat_id": "-100-runtime"},
            }
            assert delivery.message_id == 73
            assert delivery.status == "published"
            assert usage == (1, 1)
        finally:
            engine.dispose()
    finally:
        api.close()
