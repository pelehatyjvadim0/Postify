from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker


pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 9, 9, tzinfo=UTC)
PROJECT_ID = 1
CHANNEL_ID = 801


def _api():
    from postify.domain.delivery.models import PublishFailureKind
    from postify.infrastructure.repositories.sqlalchemy_delivery import (
        SqlAlchemyDeliveryRepository,
    )

    return PublishFailureKind, SqlAlchemyDeliveryRepository


def _seed_project(engine) -> None:
    """Проект и его единственный канал: доставке больше не нужны маршруты."""
    with engine.begin() as connection:
        if connection.execute(
            text("SELECT id FROM content_projects WHERE id=:id"), {"id": PROJECT_ID}
        ).scalar_one_or_none() is not None:
            return
        owner_id = connection.execute(
            text(
                "INSERT INTO users"
                "(telegram_user_id,telegram_username,display_name,created_at,is_active)"
                " VALUES ('7000001','owner','Владелец',:now,true) RETURNING id"
            ),
            {"now": NOW},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO content_projects"
                "(id,owner_id,name,project_prompt,language,audience,timezone,configuration,created_at,updated_at)"
                " VALUES (:id,:owner,'Проект','Тема','ru','Аудитория','UTC','{}'::jsonb,:now,:now)"
            ),
            {"id": PROJECT_ID, "owner": owner_id, "now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO channel_connections"
                "(id,project_id,provider,name,enabled,configuration,connection_status,created_at,updated_at)"
                " VALUES (:id,:project,'telegram','Канал',true,'{}'::jsonb,'ok',:now,:now)"
            ),
            {"id": CHANNEL_ID, "project": PROJECT_ID, "now": NOW},
        )


def _seed_post(
    engine,
    *,
    status: str = "approved",
    marker: str | None = None,
    scheduled_at: datetime | None = NOW,
    media: bool = True,
) -> int:
    marker = marker or uuid4().hex
    _seed_project(engine)
    with engine.begin() as connection:
        post_id = connection.execute(
            text(
                "INSERT INTO posts"
                "(project_id,post_text,media_path,media_mime,status,scheduled_at,created_at,updated_at)"
                " VALUES (:project,:post_text,:media_path,:media_mime,:status,:at,:now,:now)"
                " RETURNING id"
            ),
            {
                "project": PROJECT_ID,
                "post_text": f"Пост {marker}",
                "media_path": f"/media/{marker}.png" if media else None,
                "media_mime": "image/png" if media else None,
                "status": status,
                "at": scheduled_at,
                "now": NOW,
            },
        ).scalar_one()
        if scheduled_at is not None:
            # Доставка третьей волны адресуется через слот контент-плана.
            # Микросекунды сохраняют уникальность времени в старых тестах,
            # где несколько постов раньше делили одну scheduled_at.
            existing_slots = connection.execute(
                text("SELECT count(*) FROM content_plan_slots WHERE project_id=:project"),
                {"project": PROJECT_ID},
            ).scalar_one()
            slot_at = scheduled_at - timedelta(
                microseconds=max(1, 1_000_000 - existing_slots)
            )
            connection.execute(
                text(
                    "INSERT INTO content_plan_slots"
                    "(project_id,publish_at,generate_at,topic,status,post_id,created_at,updated_at)"
                    " VALUES (:project,:at,:at,'Тема','planned',:post,:now,:now)"
                ),
                {
                    "project": PROJECT_ID,
                    "post": post_id,
                    "at": slot_at,
                    "now": NOW,
                },
            )
        return post_id


def _repository(engine, **kwargs):
    _, Repository = _api()
    return Repository(
        sessionmaker(engine), PROJECT_ID, channel_id=CHANNEL_ID, **kwargs
    )


def test_reserve_next_claims_only_one_earliest_planned_approved_post(
    migrated_database_url: str,
) -> None:
    # Порядок назначенной даты важнее порядка создания; rejected не отправляется.
    engine = create_engine(migrated_database_url)
    rejected_id = _seed_post(engine, status="rejected", marker="first-rejected")
    first_id = _seed_post(engine, marker="second-approved")
    second_id = _seed_post(
        engine, marker="third-approved", scheduled_at=NOW - timedelta(seconds=1)
    )
    repository = _repository(engine)
    try:
        first = repository.reserve_next(now=NOW)
        second = repository.reserve_next(now=NOW)

        assert first is not None and first.post_id == second_id
        assert second is not None and second.post_id == first_id
        assert rejected_id not in {first.post_id, second.post_id}
        assert first.attempt_no == second.attempt_no == 1
    finally:
        engine.dispose()


def test_unplanned_and_future_posts_are_never_reserved(
    migrated_database_url: str,
) -> None:
    # Поломка: пост без времени публикации или с будущим временем уходит в канал.
    engine = create_engine(migrated_database_url)
    _seed_post(engine, marker="no-plan", scheduled_at=None)
    _seed_post(engine, marker="future", scheduled_at=NOW + timedelta(minutes=5))
    repository = _repository(engine)
    try:
        assert repository.reserve_next(now=NOW) is None
    finally:
        engine.dispose()


def test_approved_post_without_content_plan_slot_is_never_reserved(
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    post_id = _seed_post(engine, marker="orphan", scheduled_at=None)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE posts SET scheduled_at=:at WHERE id=:post"),
            {"at": NOW - timedelta(minutes=1), "post": post_id},
        )
    repository = _repository(engine)
    try:
        assert repository.reserve_next(now=NOW) is None
    finally:
        engine.dispose()


def test_disabled_project_channel_stops_delivery(migrated_database_url: str) -> None:
    # Поломка: пост уходит в канал, который владелец выключил.
    engine = create_engine(migrated_database_url)
    _seed_post(engine, marker="disabled-channel")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE channel_connections SET enabled=false WHERE id=:id"),
            {"id": CHANNEL_ID},
        )
    repository = _repository(engine)
    try:
        assert repository.reserve_next(now=NOW) is None
    finally:
        engine.dispose()


def test_two_concurrent_claims_receive_different_posts(
    migrated_database_url: str,
) -> None:
    # Поломка: удалён FOR UPDATE SKIP LOCKED и два worker берут один пост.
    engine = create_engine(migrated_database_url, pool_size=4)
    first_id = _seed_post(engine, marker="concurrent-first")
    second_id = _seed_post(engine, marker="concurrent-second")
    repository = _repository(engine)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(executor.map(lambda _: repository.reserve_next(now=NOW), range(2)))

        assert {claim.post_id for claim in claims if claim is not None} == {
            first_id,
            second_id,
        }
        assert len([claim for claim in claims if claim is not None]) == 2
    finally:
        engine.dispose()


def test_claim_skips_a_lock_held_on_the_oldest_post(
    migrated_database_url: str,
) -> None:
    # Поломка: удалённый SKIP LOCKED блокирует слот вместо выбора следующего поста.
    engine = create_engine(migrated_database_url, pool_size=3)
    first_id = _seed_post(engine, marker="locked-first")
    second_id = _seed_post(engine, marker="locked-second")
    repository = _repository(engine)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(
            text("SELECT id FROM posts WHERE id=:id FOR UPDATE"), {"id": first_id}
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            claim = executor.submit(repository.reserve_next, now=NOW).result(timeout=2)
        assert claim is not None and claim.post_id == second_id
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_delivery_has_one_row_per_post(migrated_database_url: str) -> None:
    # Поломка: удалён unique post_id и один пост получает две доставки.
    engine = create_engine(migrated_database_url)
    post_id = _seed_post(engine, marker="unique")
    repository = _repository(engine)
    try:
        repository.reserve_next(now=NOW)
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO deliveries "
                        "(project_id, post_id, channel_id, status, attempt_no,"
                        " sending_started_at, created_at, updated_at) "
                        "VALUES (:project, :post_id, :channel, 'sending', 1, :now, :now, :now)"
                    ),
                    {
                        "project": PROJECT_ID,
                        "post_id": post_id,
                        "channel": CHANNEL_ID,
                        "now": NOW,
                    },
                )
    finally:
        engine.dispose()


def test_reserved_delivery_keeps_the_channel_snapshot_of_its_attempt(
    migrated_database_url: str,
) -> None:
    # Поломка: журнал доставки теряет адрес канала после правки подключения.
    engine = create_engine(migrated_database_url)
    post_id = _seed_post(engine, marker="snapshot")
    repository = _repository(
        engine, channel_snapshot={"id": CHANNEL_ID, "configuration": {"chat_id": "@канал"}}
    )
    try:
        claim = repository.reserve_next(now=NOW)
        assert claim is not None
        with engine.connect() as connection:
            channel_id, snapshot = connection.execute(
                text(
                    "SELECT channel_id, channel_snapshot FROM deliveries WHERE post_id=:id"
                ),
                {"id": post_id},
            ).one()
        assert channel_id == CHANNEL_ID
        assert snapshot == {"id": CHANNEL_ID, "configuration": {"chat_id": "@канал"}}
    finally:
        engine.dispose()


def test_targeted_reservation_ignores_other_due_posts(
    migrated_database_url: str,
) -> None:
    # Поломка: публикация по кнопке отправляет не тот пост, который выбрал редактор.
    engine = create_engine(migrated_database_url)
    _seed_post(engine, marker="earlier", scheduled_at=NOW - timedelta(minutes=5))
    target_id = _seed_post(engine, marker="targeted")
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW, post_id=target_id)
        assert claim is not None and claim.post_id == target_id
        assert repository.reserve_next(now=NOW, post_id=target_id) is None
    finally:
        engine.dispose()


def test_retryable_is_the_only_failure_claimed_again_with_next_attempt(
    migrated_database_url: str,
) -> None:
    # Поломка: retryable теряется, terminal ретраится или attempt_no не растёт.
    FailureKind, _ = _api()
    engine = create_engine(migrated_database_url)
    retry_id = _seed_post(engine, marker="retryable")
    failed_id = _seed_post(engine, marker="failed")
    uncertain_id = _seed_post(engine, marker="uncertain")
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW)
        assert claim is not None and claim.post_id == retry_id
        repository.record_failure(
            claim, kind=FailureKind.RETRYABLE, code="retry", reason="safe", now=NOW
        )
        retry = repository.reserve_next(now=NOW + timedelta(minutes=1))
        assert retry is not None and retry.post_id == retry_id
        assert retry.attempt_no == 2
        repository.record_failure(
            retry, kind=FailureKind.FAILED, code="terminal", reason="safe", now=NOW
        )
        for expected_id, kind in (
            (failed_id, FailureKind.FAILED),
            (uncertain_id, FailureKind.UNCERTAIN),
        ):
            claim = repository.reserve_next(now=NOW + timedelta(minutes=1))
            assert claim is not None and claim.post_id == expected_id
            repository.record_failure(
                claim, kind=kind, code=f"code_{kind.value}", reason="safe", now=NOW
            )
        assert repository.reserve_next(now=NOW + timedelta(minutes=2)) is None
    finally:
        engine.dispose()


def test_earlier_planned_retryable_precedes_later_planned_new_post(
    migrated_database_url: str,
) -> None:
    # Поломка: новые посты бесконечно отодвигают ранний retryable.
    FailureKind, _ = _api()
    engine = create_engine(migrated_database_url)
    retryable_id = _seed_post(
        engine, marker="older-retryable", scheduled_at=NOW - timedelta(seconds=1)
    )
    later_id = _seed_post(engine, marker="later-new")
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW)
        assert claim is not None and claim.post_id == retryable_id
        repository.record_failure(
            claim, kind=FailureKind.RETRYABLE, code="retry", reason="safe", now=NOW
        )
        retry = repository.reserve_next(now=NOW + timedelta(minutes=1))
        assert retry is not None and retry.post_id == retryable_id
        assert retry.attempt_no == 2
        assert later_id != retry.post_id
    finally:
        engine.dispose()


def test_reservation_requires_the_enabled_channel_of_this_project(
    migrated_database_url: str,
) -> None:
    # Поломка: доставка адресуется чужим каналом и пост уходит не туда.
    _, Repository = _api()
    engine = create_engine(migrated_database_url)
    post_id = _seed_post(engine, marker="foreign-channel")
    foreign = Repository(sessionmaker(engine), PROJECT_ID, channel_id=CHANNEL_ID + 1)
    try:
        assert foreign.reserve_next(now=NOW) is None
        claim = _repository(engine).reserve_next(now=NOW)
        assert claim is not None and claim.post_id == post_id
    finally:
        engine.dispose()


def test_manual_delivery_retry_accepts_only_project_owned_retryable_delivery(
    migrated_database_url: str,
) -> None:
    # Поломка: повтор по кнопке доступен для чужой или уже отправленной доставки.
    from postify.application.delivery.manual_operations import (
        DeliveryNotRetryable,
        ManualDeliveryRetry,
    )

    FailureKind, Repository = _api()
    engine = create_engine(migrated_database_url)
    post_id = _seed_post(engine, marker="manual-delivery-retry")
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW, post_id=post_id)
        assert claim is not None
        owner = ManualDeliveryRetry(Repository(sessionmaker(engine), PROJECT_ID))
        # Доставка ещё в статусе sending: повторять нечего.
        with pytest.raises(DeliveryNotRetryable):
            owner.prepare(claim.delivery_id)

        repository.record_failure(
            claim,
            kind=FailureKind.RETRYABLE,
            code="telegram_retryable",
            reason="safe",
            now=NOW,
        )

        assert owner.prepare(claim.delivery_id) is None
        with pytest.raises(DeliveryNotRetryable):
            ManualDeliveryRetry(
                Repository(sessionmaker(engine), PROJECT_ID + 1)
            ).prepare(claim.delivery_id)
    finally:
        engine.dispose()


def test_stale_sending_becomes_uncertain_with_one_attempt(
    migrated_database_url: str,
) -> None:
    # Поломка: stale conversion пропущена или uncertain автоматически retry.
    engine = create_engine(migrated_database_url)
    post_id = _seed_post(
        engine, marker="stale", scheduled_at=NOW - timedelta(minutes=30)
    )
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW - timedelta(minutes=30))
        assert claim is not None
        changed = repository.mark_stale_sending_uncertain(
            stale_before=NOW - timedelta(minutes=10), now=NOW
        )
        with engine.connect() as connection:
            delivery = connection.execute(
                text("SELECT status, failure_code FROM deliveries WHERE post_id=:id"),
                {"id": post_id},
            ).one()
            attempt = connection.execute(
                text(
                    "SELECT attempt_no, outcome, code FROM delivery_attempts "
                    "WHERE delivery_id=:id"
                ),
                {"id": claim.delivery_id},
            ).one()

        assert changed == 1
        assert delivery == ("uncertain", "stale_sending")
        assert attempt == (1, "uncertain", "stale_sending")
        assert repository.reserve_next(now=NOW) is None
    finally:
        engine.dispose()


def test_confirmation_atomically_persists_attempt_delivery_message_and_post(
    migrated_database_url: str,
) -> None:
    # Поломка: confirm не пишет message_id/attempt/пост published в одном commit.
    engine = create_engine(migrated_database_url)
    post_id = _seed_post(engine, marker="confirmed")
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW)
        assert claim is not None
        repository.confirm_published(claim, message_id=731, now=NOW)
        with engine.connect() as connection:
            delivery = connection.execute(
                text(
                    "SELECT status, message_id, confirmed_at FROM deliveries "
                    "WHERE post_id=:id"
                ),
                {"id": post_id},
            ).one()
            attempt = connection.execute(
                text(
                    "SELECT attempt_no, outcome, message_id FROM delivery_attempts "
                    "WHERE delivery_id=:id"
                ),
                {"id": claim.delivery_id},
            ).one()
            post_status = connection.execute(
                text("SELECT status FROM posts WHERE id=:id"), {"id": post_id}
            ).scalar_one()
            history = connection.execute(
                text(
                    "SELECT status, reason FROM post_status_history WHERE post_id=:id"
                ),
                {"id": post_id},
            ).all()

        assert delivery.status == "published"
        assert delivery.message_id == 731
        assert delivery.confirmed_at == NOW
        assert attempt == (1, "published", 731)
        assert post_status == "published"
        assert history == [("published", "channel_confirmed")]
    finally:
        engine.dispose()


@pytest.mark.parametrize("message_id", [None, 0, -1, True, "731"])
def test_confirmation_rejects_missing_or_nonpositive_integer_message_id(
    migrated_database_url: str, message_id: object
) -> None:
    # Поломка: пост становится published без целочисленного подтверждения.
    engine = create_engine(migrated_database_url)
    post_id = _seed_post(engine)
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW)
        assert claim is not None
        with pytest.raises((TypeError, ValueError)):
            repository.confirm_published(claim, message_id=message_id, now=NOW)
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT status FROM posts WHERE id=:id"), {"id": post_id}
            ).scalar_one() == "approved"
    finally:
        engine.dispose()


def test_confirmation_sql_failure_rolls_back_every_write(
    migrated_database_url: str,
) -> None:
    # Поломка: ошибка INSERT попытки оставляет доставку и пост published.
    engine = create_engine(migrated_database_url)
    post_id = _seed_post(engine, marker="rollback")
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW)
        assert claim is not None
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE FUNCTION fail_delivery_attempt_insert() RETURNS trigger LANGUAGE plpgsql AS $$ "
                    "BEGIN RAISE EXCEPTION 'forced confirmation failure'; END $$"
                )
            )
            connection.execute(
                text(
                    "CREATE TRIGGER fail_delivery_attempt BEFORE INSERT ON delivery_attempts "
                    "FOR EACH ROW EXECUTE FUNCTION fail_delivery_attempt_insert()"
                )
            )

        with pytest.raises(DBAPIError):
            repository.confirm_published(claim, message_id=731, now=NOW)
        with engine.connect() as connection:
            delivery = connection.execute(
                text(
                    "SELECT status, message_id, confirmed_at, media_deleted_at "
                    "FROM deliveries WHERE post_id=:id"
                ),
                {"id": post_id},
            ).one()
            post = connection.execute(
                text("SELECT status, media_deleted_at FROM posts WHERE id=:id"),
                {"id": post_id},
            ).one()
            attempts = connection.execute(
                text("SELECT count(*) FROM delivery_attempts")
            ).scalar_one()

        assert delivery == ("sending", None, None, None)
        assert post == ("approved", None)
        assert attempts == 0
    finally:
        engine.dispose()


def test_cleanup_marker_is_persisted_separately_from_confirmation(
    migrated_database_url: str,
) -> None:
    # Поломка: подтверждение сразу помечает медиа удалённым или cleanup теряется.
    engine = create_engine(migrated_database_url)
    post_id = _seed_post(engine, marker="cleanup")
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW)
        assert claim is not None
        repository.confirm_published(claim, message_id=731, now=NOW)
        pending = repository.pending_cleanup()
        assert pending is not None and pending.post_id == post_id

        repository.mark_media_deleted(claim.delivery_id, now=NOW + timedelta(minutes=1))
        with engine.connect() as connection:
            delivery_deleted, post_deleted = connection.execute(
                text(
                    "SELECT d.media_deleted_at, p.media_deleted_at FROM deliveries d "
                    "JOIN posts p ON p.id=d.post_id WHERE d.id=:id"
                ),
                {"id": claim.delivery_id},
            ).one()

        assert delivery_deleted == NOW + timedelta(minutes=1)
        assert post_deleted == NOW + timedelta(minutes=1)
        assert repository.pending_cleanup() is None
    finally:
        engine.dispose()


def test_text_post_publication_confirms_once_without_media_cleanup(
    migrated_database_url: str,
) -> None:
    # Поломка: пост без картинки пытается удалить файл или уходит в канал дважды.
    from postify.application.delivery.publish_content import PublishContent
    from postify.domain.delivery.models import TelegramMessage

    engine = create_engine(migrated_database_url)
    post_id = _seed_post(engine, marker="text-only", media=False)
    sent: list[object] = []

    class Publisher:
        def publish(self, claim):
            sent.append(claim)
            return TelegramMessage(987)

    class Media:
        def delete(self, path):
            pytest.fail("У текстового поста нет файла для удаления")

    try:
        action = PublishContent(
            _repository(engine),
            Publisher(),
            Media(),
            timeout_seconds=60,
            clock=lambda: NOW,
        )
        assert action.execute(post_id=post_id).message_id == 987
        assert action.execute(post_id=post_id).outcome == "empty"
        assert len(sent) == 1
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT status FROM posts WHERE id=:id"), {"id": post_id}
            ).scalar_one() == "published"
    finally:
        engine.dispose()
