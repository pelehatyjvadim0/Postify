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


def _api():
    from postify.domain.delivery.models import PublishFailureKind
    from postify.infrastructure.repositories.sqlalchemy_delivery import (
        SqlAlchemyDeliveryRepository,
    )

    return PublishFailureKind, SqlAlchemyDeliveryRepository


def _seed_package(engine, *, status: str = "approved", marker: str | None = None) -> int:
    marker = marker or uuid4().hex
    with engine.begin() as connection:
        candidate_id = connection.execute(
            text(
                "INSERT INTO candidates "
                "(source_name, source_id, title, url, discovered_at, raw_payload) "
                "VALUES ('hn', :source_id, :title, :url, :now, '{}'::jsonb) RETURNING id"
            ),
            {
                "source_id": marker,
                "title": f"Candidate {marker}",
                "url": f"https://source.test/{marker}",
                "now": NOW,
            },
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO candidate_decisions "
                "(candidate_id, status, reason, explanation, signals, policy_version, decided_at) "
                "VALUES (:candidate_id, 'selected', 'eligible_for_ai', 'eligible', "
                "'{}'::jsonb, 'v1', :now)"
            ),
            {"candidate_id": candidate_id, "now": NOW},
        )
        attempt_id = connection.execute(
            text(
                "INSERT INTO content_attempts "
                "(candidate_id, attempt_no, tier, status, source_url, article_title, "
                "article_text, analysis, started_at, finished_at) "
                "VALUES (:candidate_id, 1, 'fresh', 'packaged', :url, 'title', "
                "'article', 'analysis', :now, :now) RETURNING id"
            ),
            {"candidate_id": candidate_id, "url": f"https://source.test/{marker}", "now": NOW},
        ).scalar_one()
        return connection.execute(
            text(
                "INSERT INTO content_packages "
                "(attempt_id, source_url, context, analysis, post_text, media_path, media_mime, "
                "media_source_type, media_source_url, review_required, status, created_at, updated_at) "
                "VALUES (:attempt_id, :url, 'context', 'analysis', :post_text, :media_path, "
                "'image/png', 'og', :media_url, true, :status, :now, :now) RETURNING id"
            ),
            {
                "attempt_id": attempt_id,
                "url": f"https://source.test/{marker}",
                "post_text": f"Пост {marker}",
                "media_path": f"/media/{marker}.png",
                "media_url": f"https://cdn.test/{marker}.png",
                "status": status,
                "now": NOW,
            },
        ).scalar_one()


def _repository(engine):
    _, Repository = _api()
    return Repository(sessionmaker(engine))


def test_reserve_next_claims_only_one_oldest_approved_package(
    migrated_database_url: str,
) -> None:
    # Поломка: wrong status filter, reverse FIFO или reserve two.
    engine = create_engine(migrated_database_url)
    rejected_id = _seed_package(engine, status="rejected", marker="first-rejected")
    first_id = _seed_package(engine, marker="second-approved")
    second_id = _seed_package(engine, marker="third-approved")
    repository = _repository(engine)
    try:
        first = repository.reserve_next(now=NOW)
        second = repository.reserve_next(now=NOW)

        assert first is not None and first.package_id == first_id
        assert second is not None and second.package_id == second_id
        assert rejected_id not in {first.package_id, second.package_id}
        assert first.attempt_no == second.attempt_no == 1
    finally:
        engine.dispose()


def test_two_concurrent_claims_receive_different_packages(
    migrated_database_url: str,
) -> None:
    # Поломка: удален FOR UPDATE SKIP LOCKED и два worker берут один пакет.
    engine = create_engine(migrated_database_url, pool_size=4)
    first_id = _seed_package(engine, marker="concurrent-first")
    second_id = _seed_package(engine, marker="concurrent-second")
    repository = _repository(engine)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(executor.map(lambda _: repository.reserve_next(now=NOW), range(2)))

        assert {claim.package_id for claim in claims if claim is not None} == {first_id, second_id}
        assert len([claim for claim in claims if claim is not None]) == 2
    finally:
        engine.dispose()


def test_claim_skips_a_lock_held_on_the_oldest_package(
    migrated_database_url: str,
) -> None:
    # Поломка: удалённый SKIP LOCKED блокирует слот вместо выбора следующего пакета.
    engine = create_engine(migrated_database_url, pool_size=3)
    first_id = _seed_package(engine, marker="locked-first")
    second_id = _seed_package(engine, marker="locked-second")
    repository = _repository(engine)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(text("SELECT id FROM content_packages WHERE id=:id FOR UPDATE"), {"id": first_id})
        with ThreadPoolExecutor(max_workers=1) as executor:
            claim = executor.submit(repository.reserve_next, now=NOW).result(timeout=2)
        assert claim is not None and claim.package_id == second_id
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_delivery_has_one_row_per_package(migrated_database_url: str) -> None:
    # Поломка: удалён unique package_id и один пакет получает две delivery.
    engine = create_engine(migrated_database_url)
    package_id = _seed_package(engine, marker="unique")
    repository = _repository(engine)
    try:
        repository.reserve_next(now=NOW)
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO telegram_deliveries "
                        "(package_id, status, attempt_no, sending_started_at, created_at, updated_at) "
                        "VALUES (:package_id, 'sending', 1, :now, :now, :now)"
                    ),
                    {"package_id": package_id, "now": NOW},
                )
    finally:
        engine.dispose()


def test_retryable_is_the_only_failure_claimed_again_with_next_attempt(
    migrated_database_url: str,
) -> None:
    # Поломка: retryable теряется, terminal ретраится или attempt_no не растёт.
    FailureKind, _ = _api()
    engine = create_engine(migrated_database_url)
    retry_id = _seed_package(engine, marker="retryable")
    failed_id = _seed_package(engine, marker="failed")
    uncertain_id = _seed_package(engine, marker="uncertain")
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW)
        assert claim is not None and claim.package_id == retry_id
        repository.record_failure(claim, kind=FailureKind.RETRYABLE, code="retry", reason="safe", now=NOW)
        retry = repository.reserve_next(now=NOW + timedelta(minutes=1))
        assert retry is not None and retry.package_id == retry_id
        assert retry.attempt_no == 2
        repository.record_failure(
            retry, kind=FailureKind.FAILED, code="terminal", reason="safe", now=NOW
        )
        for expected_id, kind in ((failed_id, FailureKind.FAILED), (uncertain_id, FailureKind.UNCERTAIN)):
            claim = repository.reserve_next(now=NOW + timedelta(minutes=1))
            assert claim is not None and claim.package_id == expected_id
            repository.record_failure(claim, kind=kind, code=f"code_{kind.value}", reason="safe", now=NOW)
        assert repository.reserve_next(now=NOW + timedelta(minutes=2)) is None
    finally:
        engine.dispose()


def test_older_retryable_precedes_later_new_package_in_fifo_order(migrated_database_url: str) -> None:
    # Поломка: CASE new-first бесконечно отодвигает ранний retryable поздними новыми пакетами.
    FailureKind, _ = _api()
    engine = create_engine(migrated_database_url)
    retryable_id = _seed_package(engine, marker="older-retryable")
    later_id = _seed_package(engine, marker="later-new")
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW)
        assert claim is not None and claim.package_id == retryable_id
        repository.record_failure(claim, kind=FailureKind.RETRYABLE, code="retry", reason="safe", now=NOW)
        retry = repository.reserve_next(now=NOW + timedelta(minutes=1))
        assert retry is not None and retry.package_id == retryable_id
        assert retry.attempt_no == 2
        assert later_id != retry.package_id
    finally:
        engine.dispose()


def test_stale_sending_becomes_uncertain_with_one_attempt(
    migrated_database_url: str,
) -> None:
    # Поломка: stale conversion пропущена или uncertain автоматически retry.
    engine = create_engine(migrated_database_url)
    package_id = _seed_package(engine, marker="stale")
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW - timedelta(minutes=30))
        assert claim is not None
        changed = repository.mark_stale_sending_uncertain(
            stale_before=NOW - timedelta(minutes=10), now=NOW
        )
        with engine.connect() as connection:
            delivery = connection.execute(
                text("SELECT status, failure_code FROM telegram_deliveries WHERE package_id=:id"),
                {"id": package_id},
            ).one()
            attempt = connection.execute(
                text(
                    "SELECT attempt_no, outcome, code FROM telegram_delivery_attempts "
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


def test_confirmation_atomically_persists_attempt_delivery_message_and_package(
    migrated_database_url: str,
) -> None:
    # Поломка: confirm не пишет message_id/attempt/package published в одном commit.
    engine = create_engine(migrated_database_url)
    package_id = _seed_package(engine, marker="confirmed")
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW)
        assert claim is not None
        repository.confirm_published(claim, message_id=731, now=NOW)
        with engine.connect() as connection:
            delivery = connection.execute(
                text(
                    "SELECT status, message_id, confirmed_at FROM telegram_deliveries "
                    "WHERE package_id=:id"
                ),
                {"id": package_id},
            ).one()
            attempt = connection.execute(
                text(
                    "SELECT attempt_no, outcome, message_id FROM telegram_delivery_attempts "
                    "WHERE delivery_id=:id"
                ),
                {"id": claim.delivery_id},
            ).one()
            package_status = connection.execute(
                text("SELECT status FROM content_packages WHERE id=:id"), {"id": package_id}
            ).scalar_one()
            published_history = connection.execute(
                text(
                    "SELECT count(*) FROM content_package_status_history "
                    "WHERE package_id=:id AND status='published'"
                ),
                {"id": package_id},
            ).scalar_one()

        assert delivery.status == "published"
        assert delivery.message_id == 731
        assert delivery.confirmed_at == NOW
        assert attempt == (1, "published", 731)
        assert package_status == "published"
        assert published_history == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("message_id", [None, 0, -1, True, "731"])
def test_confirmation_rejects_missing_or_nonpositive_integer_message_id(
    migrated_database_url: str, message_id: object
) -> None:
    # Поломка: package published без целочисленного confirmation.
    engine = create_engine(migrated_database_url)
    package_id = _seed_package(engine)
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW)
        assert claim is not None
        with pytest.raises((TypeError, ValueError)):
            repository.confirm_published(claim, message_id=message_id, now=NOW)
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT status FROM content_packages WHERE id=:id"), {"id": package_id}
            ).scalar_one() == "approved"
    finally:
        engine.dispose()


def test_confirmation_sql_failure_rolls_back_every_write(
    migrated_database_url: str,
) -> None:
    # Поломка: attempt INSERT failure оставляет delivery/package published.
    engine = create_engine(migrated_database_url)
    package_id = _seed_package(engine, marker="rollback")
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW)
        assert claim is not None
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE FUNCTION fail_telegram_attempt_insert() RETURNS trigger LANGUAGE plpgsql AS $$ "
                    "BEGIN RAISE EXCEPTION 'forced confirmation failure'; END $$"
                )
            )
            connection.execute(
                text(
                    "CREATE TRIGGER fail_telegram_attempt BEFORE INSERT ON telegram_delivery_attempts "
                    "FOR EACH ROW EXECUTE FUNCTION fail_telegram_attempt_insert()"
                )
            )

        with pytest.raises(DBAPIError):
            repository.confirm_published(claim, message_id=731, now=NOW)
        with engine.connect() as connection:
            delivery = connection.execute(
                text(
                    "SELECT status, message_id, confirmed_at, media_deleted_at "
                    "FROM telegram_deliveries WHERE package_id=:id"
                ),
                {"id": package_id},
            ).one()
            package = connection.execute(
                text("SELECT status, media_deleted_at FROM content_packages WHERE id=:id"),
                {"id": package_id},
            ).one()
            attempts = connection.execute(
                text("SELECT count(*) FROM telegram_delivery_attempts")
            ).scalar_one()

        assert delivery == ("sending", None, None, None)
        assert package == ("approved", None)
        assert attempts == 0
    finally:
        engine.dispose()


def test_cleanup_marker_is_persisted_separately_from_confirmation(
    migrated_database_url: str,
) -> None:
    # Поломка: confirmation сразу помечает медиа удалённым или cleanup теряется.
    engine = create_engine(migrated_database_url)
    package_id = _seed_package(engine, marker="cleanup")
    repository = _repository(engine)
    try:
        claim = repository.reserve_next(now=NOW)
        assert claim is not None
        repository.confirm_published(claim, message_id=731, now=NOW)
        pending = repository.pending_cleanup()
        assert pending is not None and pending.package_id == package_id

        repository.mark_media_deleted(claim.delivery_id, now=NOW + timedelta(minutes=1))
        with engine.connect() as connection:
            delivery_deleted, package_deleted = connection.execute(
                text(
                    "SELECT d.media_deleted_at, p.media_deleted_at FROM telegram_deliveries d "
                    "JOIN content_packages p ON p.id=d.package_id WHERE d.id=:id"
                ),
                {"id": claim.delivery_id},
            ).one()

        assert delivery_deleted == NOW + timedelta(minutes=1)
        assert package_deleted == NOW + timedelta(minutes=1)
        assert repository.pending_cleanup() is None
    finally:
        engine.dispose()
