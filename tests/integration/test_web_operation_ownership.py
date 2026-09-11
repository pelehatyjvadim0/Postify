"""Владение длительной операцией переживает перезапуск процесса.

Пул операций живёт в памяти инстанса, поэтому единственный общий арбитр —
``operation_runs`` с частичным уникальным индексом по running. Тесты идут на
настоящей базе: именно она отвечает за «занято» и за однократное выполнение
принятой задачи планировщика.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import json
from threading import Event

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from postify.config import Settings
from postify.domain.projects.models import ProjectConfiguration
from postify.web.services import WebApplication


pytestmark = pytest.mark.integration


NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
PROJECT = 1
POST = 77
DELIVERY = 5
CONFIGURATION = json.dumps(
    asdict(
        ProjectConfiguration(media_max_bytes=10_000_000, analysis_timeout_seconds=60)
    )
)


class PublishResult:
    """То, что возвращает публикация: фасаду нужен только ``outcome``."""

    outcome = "published"


def _settings(database_url: str, tmp_path) -> Settings:
    return Settings(
        database_url=database_url,
        content_media_dir=tmp_path,
        postify_secret_key=SecretStr(Fernet.generate_key().decode("ascii")),
    )


def _seed(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users(id,telegram_user_id,telegram_username,"
                "display_name,created_at,is_active)"
                " VALUES (1,'101','user_101','Владелец',:now,true)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO content_projects(id,name,project_prompt,language,audience,"
                "timezone,configuration,created_at,updated_at,owner_id)"
                " VALUES (:project,'Агротех','Агротех','ru','Фермеры',"
                "'Europe/Moscow',CAST(:configuration AS jsonb),:now,:now,1)"
            ),
            {"project": PROJECT, "configuration": CONFIGURATION, "now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO posts(id,project_id,post_text,status,scheduled_at,"
                "generation,created_at,updated_at)"
                " VALUES (:post,:project,'Текст','approved',:now,'{}'::jsonb,:now,:now)"
            ),
            {"post": POST, "project": PROJECT, "now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO deliveries(id,project_id,post_id,status,attempt_no,"
                "sending_started_at,created_at,updated_at)"
                " VALUES (:delivery,:project,:post,'retryable',1,:now,:now,:now)"
            ),
            {"delivery": DELIVERY, "project": PROJECT, "post": POST, "now": NOW},
        )


def _operation_rows(database_url: str, operation: str):
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return connection.execute(
                text(
                    "SELECT status,outcome FROM operation_runs"
                    " WHERE project_id=:project AND operation=:operation ORDER BY id"
                ),
                {"project": PROJECT, "operation": operation},
            ).all()
    finally:
        engine.dispose()


def test_two_web_instances_share_durable_operation_ownership(
    migrated_database_url: str, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Поломка: два process-local пула принимают одну и ту же работу.
    from postify.web import services

    started = Event()
    release = Event()

    class BlockingPublish:
        def execute(self, *, post_id=None, delivery_id=None):
            started.set()
            assert release.wait(timeout=2)
            return PublishResult()

    @contextmanager
    def opened(*args, **kwargs):
        assert kwargs["record_operation"] is False
        yield BlockingPublish()

    monkeypatch.setattr(services, "open_project_publish_once", opened)
    engine = create_engine(migrated_database_url)
    _seed(engine)
    engine.dispose()
    settings = _settings(migrated_database_url, tmp_path)
    first = WebApplication(settings)
    second = WebApplication(settings)
    try:
        accepted = first.retry_delivery(PROJECT, DELIVERY)
        assert accepted["status"] == "running"
        assert started.wait(timeout=2)

        with pytest.raises(RuntimeError, match="operation_busy"):
            second.retry_delivery(PROJECT, DELIVERY)

        release.set()
        first.close()
        second.close()
    finally:
        release.set()
        # close идемпотентен: повтор после раннего провала assert безопасен.
        first.close()
        second.close()

    assert _operation_rows(migrated_database_url, "retry_delivery") == [
        ("succeeded", "published")
    ]


def test_restarted_worker_executes_accepted_scheduler_job_exactly_once(
    migrated_database_url: str, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Поломка: принятая до перезапуска задача теряется или выполняется дважды.
    from postify.application.scheduling.project_scheduler import ScheduledCommand
    from postify.web import services

    executions: list[int | None] = []

    class Publish:
        def execute(self, *, post_id=None, delivery_id=None):
            executions.append(post_id)
            return PublishResult()

    @contextmanager
    def opened(*args, **kwargs):
        yield Publish()

    monkeypatch.setattr(services, "open_project_publish_once", opened)
    engine = create_engine(migrated_database_url)
    _seed(engine)
    engine.dispose()
    settings = _settings(migrated_database_url, tmp_path)
    first = WebApplication(settings)
    scheduled_for = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(
        minutes=1
    )
    accepted = first._schedule_repository.accept(
        ScheduledCommand(PROJECT, "publish_once", scheduled_for, post_id=POST)
    )
    assert accepted is not None
    first.close()

    restarted = WebApplication(settings)
    try:
        restarted.scheduler_tick()
    finally:
        restarted.close()

    assert executions == [POST]
    engine = create_engine(migrated_database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT status,attempt_count FROM scheduled_jobs WHERE id=:id"
                ),
                {"id": accepted.job_id},
            ).one() == ("succeeded", 1)
    finally:
        engine.dispose()
    assert _operation_rows(migrated_database_url, "publish_once") == [
        ("succeeded", "published")
    ]
