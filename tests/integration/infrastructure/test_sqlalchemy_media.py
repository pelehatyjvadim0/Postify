"""Пул изображений в настоящей PostgreSQL с расширением vector.

Проверяется то, что нельзя проверить на подставном репозитории: дедупликация
уникальным индексом, политика повторов в SQL, векторное расстояние и изоляция
по проекту.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from postify.infrastructure.repositories.sqlalchemy_media import (
    SqlAlchemyMediaRepository,
)


pytestmark = pytest.mark.integration


# Цепочка ревизий в этой волне разветвлена: 03, 04 и 05 стоят на 02. Поэтому
# цель — "heads" (все ветки), а не "head": после сведения цепочки в линию она
# продолжит работать без правки.
TARGET = "heads"

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
MINE = 1
FOREIGN = 2
DIMENSIONS = 768


def vector(axis: int) -> tuple[float, ...]:
    """Единичный вектор по одной оси: расстояния между такими предсказуемы."""
    values = [0.0] * DIMENSIONS
    values[axis] = 1.0
    return tuple(values)


@pytest.fixture
def engine(alembic_config: Config, isolated_database_url: str):
    command.upgrade(alembic_config, TARGET)
    engine = create_engine(isolated_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users(id,telegram_user_id,telegram_username,"
                    "display_name,created_at,is_active)"
                    " VALUES (1,'101','','',:now,true)"
                ),
                {"now": NOW},
            )
            # Трек промптов переименовывает колонку темы проекта, и сюда
            # тест приходит и до, и после этой ревизии.
            prompt = (
                "project_prompt"
                if connection.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns"
                        " WHERE table_schema = current_schema()"
                        " AND table_name='content_projects'"
                        " AND column_name='project_prompt' LIMIT 1"
                    )
                ).scalar_one_or_none()
                else "topic"
            )
            for project_id in (MINE, FOREIGN):
                connection.execute(
                    text(
                        f"INSERT INTO content_projects(id,owner_id,name,{prompt},"
                        "language,audience,timezone,configuration,created_at,updated_at)"
                        " VALUES (:id,1,:name,'Тема','ru','Все','UTC','{}'::jsonb,"
                        ":now,:now)"
                    ),
                    {"id": project_id, "name": f"Проект {project_id}", "now": NOW},
                )
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def repository(engine):
    return SqlAlchemyMediaRepository(sessionmaker(engine), MINE)


@pytest.fixture
def foreign(engine):
    return SqlAlchemyMediaRepository(sessionmaker(engine), FOREIGN)


def add(repository, *, content_hash: str, now: datetime = NOW) -> int:
    asset_id, created = repository.create(
        file_path=f"/var/media/pool/{content_hash}.png",
        thumb_path=f"/var/media/pool/{content_hash}_thumb.jpg",
        mime="image/png",
        bytes=1024,
        width=1600,
        height=900,
        content_hash=content_hash,
        now=now,
    )
    assert created
    return asset_id


def caption(repository, asset_id: int, *, text_value: str, axis: int, model="mock"):
    repository.save_caption(
        asset_id,
        caption=text_value,
        caption_model=model,
        embedding=vector(axis),
        now=NOW,
    )


def test_same_content_is_not_duplicated_inside_a_project(repository, foreign) -> None:
    first = add(repository, content_hash="hash-a")

    again = repository.create(
        file_path="/var/media/pool/hash-a.png",
        thumb_path=None,
        mime="image/png",
        bytes=1024,
        width=10,
        height=10,
        content_hash="hash-a",
        now=NOW,
    )
    # Тот же файл в другом проекте — другой актив: пулы независимы.
    other = add(foreign, content_hash="hash-a")

    assert again == (first, False)
    assert other != first
    assert repository.counts(now=NOW).total == 1


def test_freshly_uploaded_asset_is_not_available_until_it_has_a_caption(
    repository,
) -> None:
    asset_id = add(repository, content_hash="hash-a")

    pending = repository.get(asset_id, now=NOW)
    caption(repository, asset_id, text_value="Силосы на закате", axis=0)
    ready = repository.get(asset_id, now=NOW)

    assert pending.caption_status == "pending"
    assert pending.available is False
    assert ready.caption_status == "ready"
    assert ready.caption_model == "mock"
    assert ready.available is True
    assert repository.counts(now=NOW) == type(repository.counts(now=NOW))(
        total=1, available=1
    )


def test_failed_provider_leaves_the_asset_without_caption(repository) -> None:
    asset_id = add(repository, content_hash="hash-a")

    repository.mark_caption_failed(asset_id)
    asset = repository.get(asset_id, now=NOW)

    assert asset.caption_status == "failed"
    assert asset.caption is None
    assert asset.available is False


def test_list_filters_by_availability_and_caption_text(repository) -> None:
    silos = add(repository, content_hash="hash-a")
    tractor = add(repository, content_hash="hash-b")
    add(repository, content_hash="hash-c")
    caption(repository, silos, text_value="Металлические силосы", axis=0)
    caption(repository, tractor, text_value="Трактор в поле", axis=1)

    available = repository.list(now=NOW, available=True)
    found = repository.list(now=NOW, query="силос")

    assert [item.id for item in available.items] == [tractor, silos]
    assert [item.id for item in found.items] == [silos]


def test_list_pages_by_cursor(repository) -> None:
    ids = [add(repository, content_hash=f"hash-{index}") for index in range(3)]

    first = repository.list(now=NOW, limit=2)
    second = repository.list(now=NOW, limit=2, cursor=first.next_cursor)

    assert [item.id for item in first.items] == [ids[2], ids[1]]
    assert first.next_cursor == str(ids[1])
    assert [item.id for item in second.items] == [ids[0]]
    assert second.next_cursor is None


def test_shortlist_orders_by_distance_and_honours_the_reuse_policy(
    repository, engine
) -> None:
    near = add(repository, content_hash="hash-near")
    far = add(repository, content_hash="hash-far")
    recent = add(repository, content_hash="hash-recent")
    caption(repository, near, text_value="Силосы", axis=0)
    caption(repository, far, text_value="Трактор", axis=1)
    caption(repository, recent, text_value="Поле", axis=0)
    _seed_post(engine, post_id=77)
    # Использовано вчера при политике 30 дней — предлагать нельзя (риск Р3).
    repository.mark_used(recent, post_id=77, now=NOW - timedelta(days=1))

    candidates = repository.shortlist(vector(0), now=NOW, limit=5)

    assert [item.asset.id for item in candidates] == [near, far]
    assert candidates[0].distance < candidates[1].distance


def test_reuse_policy_releases_the_asset_after_media_reuse_days(
    repository, engine
) -> None:
    asset_id = add(repository, content_hash="hash-a")
    caption(repository, asset_id, text_value="Силосы", axis=0)
    _seed_post(engine, post_id=77)
    repository.mark_used(asset_id, post_id=77, now=NOW - timedelta(days=31))

    released = repository.shortlist(vector(0), now=NOW, limit=5)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE content_projects SET media_reuse_days=60 WHERE id=:id"),
            {"id": MINE},
        )
    still_locked = repository.shortlist(vector(0), now=NOW, limit=5)

    assert [item.asset.id for item in released] == [asset_id]
    assert still_locked == ()


def test_usage_is_recorded_for_the_project_and_the_post(repository, engine) -> None:
    asset_id = add(repository, content_hash="hash-a")
    _seed_post(engine, post_id=77)

    repository.mark_used(asset_id, post_id=77, now=NOW)
    asset = repository.get(asset_id, now=NOW)
    with engine.connect() as connection:
        usages = connection.execute(
            text("SELECT project_id, asset_id, post_id FROM media_usages")
        ).all()

    assert asset.use_count == 1
    assert asset.last_used_at == NOW
    assert usages == [(MINE, asset_id, 77)]


def test_manual_caption_is_not_reissued_with_the_mock_ones(repository) -> None:
    mocked = add(repository, content_hash="hash-a")
    edited = add(repository, content_hash="hash-b")
    caption(repository, mocked, text_value="Подпись-заглушка", axis=0)
    caption(repository, edited, text_value="Подпись-заглушка", axis=1)

    repository.update(edited, caption="Силосы, снято с дрона", now=NOW)
    stale = repository.ids_captioned_by("mock")
    after = repository.get(edited, now=NOW)

    assert stale == (mocked,)
    assert after.caption_model == "manual"
    # Вектор посчитан по старому тексту, поэтому в подбор актив не идёт.
    assert after.has_embedding is False
    assert after.available is False


def test_reissued_caption_replaces_the_mock_one(repository) -> None:
    asset_id = add(repository, content_hash="hash-a")
    caption(repository, asset_id, text_value="Подпись-заглушка", axis=0)

    caption(
        repository,
        asset_id,
        text_value="Силосы на закате",
        axis=1,
        model="openai/text-embedding-3-small",
    )
    asset = repository.get(asset_id, now=NOW)

    assert repository.ids_captioned_by("mock") == ()
    assert asset.caption_model == "openai/text-embedding-3-small"
    assert asset.available is True


def test_foreign_asset_is_invisible_and_unchangeable(repository, foreign) -> None:
    # Изоляция данных: чужой asset_id обязан выглядеть несуществующим.
    theirs = add(foreign, content_hash="hash-theirs")
    caption(foreign, theirs, text_value="Чужие силосы", axis=0)

    with pytest.raises(LookupError):
        repository.get(theirs, now=NOW)
    with pytest.raises(LookupError):
        repository.update(theirs, enabled=False, now=NOW)
    with pytest.raises(LookupError):
        repository.delete(theirs)
    with pytest.raises(LookupError):
        repository.file(theirs, thumb=False)

    assert repository.list(now=NOW).items == ()
    assert repository.shortlist(vector(0), now=NOW, limit=5) == ()
    assert foreign.get(theirs, now=NOW).id == theirs


def test_disabled_asset_leaves_the_pool_but_stays_listed(repository) -> None:
    asset_id = add(repository, content_hash="hash-a")
    caption(repository, asset_id, text_value="Силосы", axis=0)

    repository.update(asset_id, enabled=False, now=NOW)

    assert repository.shortlist(vector(0), now=NOW, limit=5) == ()
    assert [item.id for item in repository.list(now=NOW).items] == [asset_id]
    assert repository.counts(now=NOW).available == 0


def test_delete_returns_the_paths_to_remove_from_disk(repository) -> None:
    asset_id = add(repository, content_hash="hash-a")

    paths = repository.delete(asset_id)

    assert paths == (
        "/var/media/pool/hash-a.png",
        "/var/media/pool/hash-a_thumb.jpg",
    )
    with pytest.raises(LookupError):
        repository.get(asset_id, now=NOW)


def _seed_post(engine, *, post_id: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO posts(id,project_id,post_text,status,created_at,updated_at)"
                " VALUES (:id,:project,'Текст','needs_review',:now,:now)"
            ),
            {"id": post_id, "project": MINE, "now": NOW},
        )
