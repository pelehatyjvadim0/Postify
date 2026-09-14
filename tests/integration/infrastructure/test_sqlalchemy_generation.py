"""Атомарная привязка результата генерации к слоту и медиа-пулу."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from postify.application.generation.models import GeneratedContent, GenerationError
from postify.application.ports.validation import DraftMedia
from postify.infrastructure.repositories.sqlalchemy_generation import (
    SqlAlchemyGenerationRepository,
)


pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 12, 10, tzinfo=UTC)


@pytest.fixture
def engine(alembic_config: Config, isolated_database_url: str):
    command.upgrade(alembic_config, "heads")
    engine = create_engine(isolated_database_url)
    try:
        _seed(engine)
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def repository(engine):
    return SqlAlchemyGenerationRepository(sessionmaker(engine), 1)


def _seed(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users(id,telegram_user_id,telegram_username,display_name,"
                "created_at,is_active) VALUES (1,'101','','Редактор',:now,true)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO user_settings(user_id,common_prompt,updated_at) "
                "VALUES (1,'Общий промпт',:now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                "UPDATE app_settings SET system_prompt='Системный промпт',"
                "updated_at=:now WHERE id=1"
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO content_projects"
                "(id,owner_id,name,project_prompt,language,audience,timezone,"
                "configuration,publication_mode,created_at,updated_at) VALUES "
                "(1,1,'Агротех','Промпт проекта','ru','Агрономы','Europe/Moscow',"
                "CAST(:configuration AS jsonb),'review',:now,:now)"
            ),
            {
                "configuration": '{"analysis_model":"gpt-project",'
                '"analysis_reasoning_effort":"high"}',
                "now": NOW,
            },
        )
        connection.execute(
            text(
                "INSERT INTO project_rubrics"
                "(id,project_id,name,instructions,enabled,created_at,updated_at) "
                "VALUES (1,1,'Подборка','Пять пунктов',true,:now,:now)"
            ),
            {"now": NOW},
        )
        for slot_id, topic, offset in (
            (41, "5 ошибок хранения зерна", 1),
            (42, "Подготовка силосов", 2),
        ):
            publish_at = NOW + timedelta(days=offset)
            connection.execute(
                text(
                    "INSERT INTO content_plan_slots"
                    "(id,project_id,publish_at,generate_at,rubric_id,topic,status,"
                    "created_at,updated_at) VALUES "
                    "(:id,1,:publish_at,:generate_at,1,:topic,'planned',:now,:now)"
                ),
                {
                    "id": slot_id,
                    "publish_at": publish_at,
                    "generate_at": publish_at - timedelta(days=1),
                    "topic": topic,
                    "now": NOW,
                },
            )
        connection.execute(
            text(
                "INSERT INTO media_assets"
                "(id,project_id,file_path,mime,bytes,width,height,content_hash,"
                "caption,caption_model,caption_status,uploaded_at,enabled) VALUES "
                "(9,1,'/media/9.jpg','image/jpeg',100,10,10,'hash-9','Силосы',"
                "'vision','ready',:now,true)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                "UPDATE media_assets SET embedding=CAST(:embedding AS vector)"
                " WHERE id=9"
            ),
            {"embedding": "[" + ",".join(["1"] + ["0"] * 767) + "]"},
        )


def test_reads_all_context_and_atomically_completes_post(repository, engine) -> None:
    brief = repository.brief_for_slot(41)
    post_id = repository.begin_generation(41, now=NOW)
    repository.complete(
        post_id,
        content=GeneratedContent("Готовый пост", 9, "На фото силосы"),
        media=DraftMedia(9, "/media/9.jpg", "image/jpeg", "Силосы"),
        generation={"provider": "codex", "iterations": 1},
        now=NOW,
    )

    with engine.connect() as connection:
        post = connection.execute(
            text(
                "SELECT post_text,status,scheduled_at,media_path,generation "
                "FROM posts WHERE id=:id"
            ),
            {"id": post_id},
        ).mappings().one()
        slot_post = connection.execute(
            text("SELECT post_id FROM content_plan_slots WHERE id=41")
        ).scalar_one()
        usage = connection.execute(
            text("SELECT asset_id,post_id FROM media_usages")
        ).one_or_none()
        use_count = connection.execute(
            text("SELECT use_count FROM media_assets WHERE id=9")
        ).scalar_one()

    assert brief.system_prompt == "Системный промпт"
    assert brief.common_prompt == "Общий промпт"
    assert brief.project_prompt == "Промпт проекта"
    assert brief.slot.rubric_instructions == "Пять пунктов"
    assert brief.slot.publish_at.utcoffset() == timedelta(hours=3)
    assert [item.topic for item in brief.plan] == ["Подготовка силосов"]
    assert (brief.model, brief.reasoning_effort) == ("gpt-project", "high")
    assert post["post_text"] == "Готовый пост"
    assert post["status"] == "needs_review"
    assert post["scheduled_at"] == NOW + timedelta(days=1)
    assert post["media_path"] == "/media/9.jpg"
    assert post["generation"] == {"provider": "codex", "iterations": 1}
    assert slot_post == post_id
    assert usage is None
    assert use_count == 0


def test_regeneration_resets_status_and_failure_is_visible(repository, engine) -> None:
    post_id = repository.begin_generation(41, now=NOW)
    repository.complete(
        post_id,
        content=GeneratedContent("Первая версия", 9, "Силосы"),
        media=DraftMedia(9, "/media/9.jpg", "image/jpeg", "Силосы"),
        generation={},
        now=NOW,
    )

    repository.begin_regeneration(post_id, now=NOW)
    repository.fail(post_id, now=NOW)

    assert repository.brief_for_post(post_id).slot.slot_id == 41
    with engine.connect() as connection:
        status = connection.execute(
            text("SELECT status FROM posts WHERE id=:id"), {"id": post_id}
        ).scalar_one()
        history = connection.execute(
            text(
                "SELECT status FROM post_status_history WHERE post_id=:id ORDER BY id"
            ),
            {"id": post_id},
        ).scalars().all()
    assert status == "failed"
    assert history == ["generating", "needs_review", "generating", "failed"]


def test_second_generation_cannot_replace_the_slot_post(repository) -> None:
    repository.begin_generation(41, now=NOW)

    with pytest.raises(GenerationError) as caught:
        repository.begin_generation(41, now=NOW)

    assert caught.value.code == "post_already_generated"
