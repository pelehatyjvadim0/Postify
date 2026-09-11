"""Ручные операции переживают рестарт как явный отказ с возможностью повтора."""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from postify.domain.observability.models import OperationKind
from postify.infrastructure.repositories.sqlalchemy_generation import SqlAlchemyGenerationRepository
from postify.infrastructure.repositories.sqlalchemy_observability import SqlAlchemyOperationRunRepository
from postify.web.app import create_app
from postify.web.dependencies import WebContainer
from postify.web.services import WebApplication
from tests.integration.test_generation_delivery_workflow import (
    _create_slot, _upload_image, _wait_operation, workflow,
)
from tests.unit.web.test_api import ApiClient, AuthStub


pytestmark = pytest.mark.integration


def test_startup_recovers_manual_generation_and_caption_and_allows_retry(workflow):
    client, api, engine, provider, current_time, requests = workflow
    asset_id = _upload_image(client, provider)
    slot_id = _create_slot(client)
    sessions = sessionmaker(engine)
    journal = SqlAlchemyOperationRunRepository(sessions, 1)
    generation_run = journal.start(
        OperationKind.GENERATE_POST, now=current_time[0], mode="manual", actor="user"
    )
    caption_run = journal.start(
        OperationKind.CAPTION_MEDIA, now=current_time[0], mode="manual", actor="user"
    )
    post_id = SqlAlchemyGenerationRepository(sessions, 1).begin_generation(
        slot_id, now=current_time[0]
    )
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE media_assets SET caption_status='pending',embedding=NULL WHERE id=:id"),
            {"id": asset_id},
        )
    api.close()
    restarted = WebApplication(api._settings)
    app = create_app(WebContainer(api=restarted), auth=AuthStub(owned=(1,)))
    client = ApiClient(app)

    def assert_recovered_and_retry():
        for run_id in (generation_run, caption_run):
            operation = client.get(f"/api/projects/1/operations/{run_id}").json()
            assert operation["status"] == "failed"
            assert operation["finished_at"] is not None
        post = client.get(f"/api/projects/1/posts/{post_id}").json()
        assert post["status"] == "failed"
        assert post["history"][-1]["reason"] == "operation_interrupted"
        asset, = client.get("/api/projects/1/media").json()["items"]
        assert asset["caption_status"] == "failed"
        captioned = client.post(f"/api/projects/1/media/{asset_id}/recaption")
        assert captioned.status_code == 202, captioned.text
        _wait_operation(client, captioned.json()["operation_id"])
        regenerated = client.post(f"/api/projects/1/posts/{post_id}/regenerate")
        assert regenerated.status_code == 202, regenerated.text
        _wait_operation(client, regenerated.json()["operation_id"])
        assert client.get(f"/api/projects/1/posts/{post_id}").json()["status"] == "needs_review"

    async def restart():
        async with app.router.lifespan_context(app):
            await asyncio.to_thread(assert_recovered_and_retry)

    asyncio.run(restart())


def test_manual_recovery_preserves_scheduled_generation(workflow):
    client, api, engine, provider, current_time, requests = workflow
    from postify.application.scheduling.project_scheduler import ScheduledCommand

    slot_id = _create_slot(client)
    sessions = sessionmaker(engine)
    scheduled = api._schedule_repository.accept(ScheduledCommand(
        1, "generate_post", current_time[0], slot_id=slot_id
    ))
    scheduled_post = SqlAlchemyGenerationRepository(sessions, 1).begin_generation(
        slot_id, now=current_time[0]
    )
    manual_run = SqlAlchemyOperationRunRepository(sessions, 1).start(
        OperationKind.REGENERATE_POST, now=current_time[0], mode="manual", actor="user"
    )

    assert api.recover_interrupted_operations() == 1

    assert client.get(f"/api/projects/1/operations/{manual_run}").json()["status"] == "failed"
    assert client.get(f"/api/projects/1/operations/{scheduled.operation_run_id}").json()["status"] == "running"
    assert client.get(f"/api/projects/1/posts/{scheduled_post}").json()["status"] == "generating"
    assert api.recover_interrupted_operations() == 0


def test_scheduler_resumes_interrupted_generation_into_the_same_post(workflow):
    client, api, engine, provider, current_time, _ = workflow
    from postify.application.scheduling.project_scheduler import ScheduledCommand

    _upload_image(client, provider)
    slot_id = _create_slot(client)
    scheduled = api._schedule_repository.accept(ScheduledCommand(
        1, "generate_post", current_time[0], slot_id=slot_id
    ))
    api._schedule_repository.claim_job(scheduled.job_id, now=current_time[0])
    post_id = SqlAlchemyGenerationRepository(sessionmaker(engine), 1).begin_generation(
        slot_id, now=current_time[0]
    )
    api.close()
    current_time[0] += timedelta(minutes=6)
    restarted = WebApplication(api._settings)
    client = ApiClient(create_app(WebContainer(api=restarted), auth=AuthStub(owned=(1,))))
    try:
        commands = restarted.scheduler_tick()
        assert len(commands) == 1
        operation = _wait_operation(client, scheduled.operation_run_id)
        assert operation["result"]["post_id"] == post_id
        assert client.get(f"/api/projects/1/posts/{post_id}").json()["status"] == "needs_review"
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM posts WHERE project_id=1")).scalar_one() == 1
    finally:
        restarted.close()
