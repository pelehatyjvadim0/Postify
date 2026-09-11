"""Хранилище входа на настоящей PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from postify.domain.auth.models import hash_session_token
from postify.infrastructure.repositories.sqlalchemy_users import (
    SqlAlchemyUserRepository,
)


pytestmark = pytest.mark.integration


NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)
EXPIRES = NOW + timedelta(minutes=10)


@pytest.fixture
def engine(migrated_database_url: str):
    engine = create_engine(migrated_database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def repository(engine):
    return SqlAlchemyUserRepository(sessionmaker(engine, expire_on_commit=False))


def make_request(repository, *, ip: str = "10.0.0.1", suffix: str = "a"):
    return repository.create_login_request(
        telegram_token=f"telegram-{suffix}",
        browser_token=f"browser-{suffix}",
        ip=ip,
        now=NOW,
        expires_at=EXPIRES,
    )


def test_user_is_created_once_and_updated_on_the_next_login(repository) -> None:
    created = repository.ensure_user(
        telegram_user_id="101",
        telegram_username="user_101",
        display_name="Иван Петров",
        now=NOW,
    )

    again = repository.ensure_user(
        telegram_user_id="101",
        telegram_username="ivan",
        display_name="Иван П.",
        now=LATER,
    )

    assert again.id == created.id
    assert again.display_name == "Иван П."
    assert again.last_login_at == LATER
    assert repository.user_by_telegram_id("101").id == created.id
    assert repository.user_by_telegram_id("202") is None


def test_login_request_moves_through_confirmation_to_approved(repository) -> None:
    request = make_request(repository)
    assert request.status == "pending"

    confirmed = repository.mark_confirmation(
        telegram_token="telegram-a",
        telegram_user_id="101",
        telegram_username="user_101",
        display_name="Иван Петров",
        now=NOW,
    )
    assert confirmed.status == "confirmation"

    decided = repository.decide(
        telegram_token="telegram-a",
        status="approved",
        telegram_user_id="101",
        now=LATER,
    )

    assert decided.status == "approved"
    assert decided.decided_at == LATER
    assert repository.login_request_by_browser_token("browser-a").status == "approved"
    assert repository.login_request_by_telegram_token("telegram-a").id == request.id


def test_foreign_telegram_user_cannot_decide_the_request(repository) -> None:
    # Поломка: без сверки id перехвативший ссылку подтверждает чужой вход.
    make_request(repository)
    repository.mark_confirmation(
        telegram_token="telegram-a",
        telegram_user_id="101",
        telegram_username="user_101",
        display_name="Иван",
        now=NOW,
    )

    assert (
        repository.decide(
            telegram_token="telegram-a",
            status="approved",
            telegram_user_id="202",
            now=LATER,
        )
        is None
    )
    assert repository.login_request_by_browser_token("browser-a").status == "confirmation"


def test_expired_request_is_neither_confirmed_nor_decided(repository) -> None:
    make_request(repository)
    after = EXPIRES + timedelta(seconds=1)

    assert (
        repository.mark_confirmation(
            telegram_token="telegram-a",
            telegram_user_id="101",
            telegram_username="user_101",
            display_name="Иван",
            now=after,
        )
        is None
    )

    repository.purge_expired(after)

    assert repository.login_request_by_browser_token("browser-a") is None


def test_tokens_are_unique(repository) -> None:
    make_request(repository)

    with pytest.raises(IntegrityError):
        repository.create_login_request(
            telegram_token="telegram-a",
            browser_token="browser-b",
            ip="10.0.0.2",
            now=NOW,
            expires_at=EXPIRES,
        )


def test_status_is_constrained_by_the_database(repository, engine) -> None:
    make_request(repository)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE login_requests SET status = 'мусор'"
                    " WHERE browser_token = 'browser-a'"
                )
            )


def test_failed_attempts_are_counted_per_ip_and_window(repository) -> None:
    make_request(repository, suffix="a")
    make_request(repository, suffix="b")
    make_request(repository, ip="10.0.0.2", suffix="c")
    repository.mark_confirmation(
        telegram_token="telegram-b",
        telegram_user_id="101",
        telegram_username="user_101",
        display_name="Иван",
        now=NOW,
    )
    repository.decide(
        telegram_token="telegram-b",
        status="approved",
        telegram_user_id="101",
        now=NOW,
    )

    window = NOW - timedelta(minutes=5)

    # approved в счётчик не попадает: успешный вход лимит не расходует.
    assert repository.failed_attempts(ip="10.0.0.1", since=window) == 1
    assert repository.failed_attempts(ip="10.0.0.2", since=window) == 1
    assert repository.failed_attempts(ip="10.0.0.1", since=NOW + timedelta(minutes=1)) == 0
    assert repository.failed_attempts(ip=None, since=window) == 0
    assert repository.active_login_requests(NOW) == 3


def test_session_is_found_by_hash_and_dies_with_its_ttl(repository) -> None:
    user = repository.ensure_user(
        telegram_user_id="101",
        telegram_username="user_101",
        display_name="Иван",
        now=NOW,
    )
    token = "открытый-токен-сессии"
    token_hash = hash_session_token(token)
    repository.create_session(
        user_id=user.id, token_hash=token_hash, now=NOW, expires_at=EXPIRES
    )

    assert repository.session_user(token_hash=token_hash, now=LATER) == user
    # В базе лежит только хеш: по открытому токену ничего не находится.
    assert repository.session_user(token_hash=token, now=LATER) is None
    assert (
        repository.session_user(
            token_hash=token_hash, now=EXPIRES + timedelta(seconds=1)
        )
        is None
    )

    repository.delete_session(token_hash)
    assert repository.session_user(token_hash=token_hash, now=LATER) is None


def test_session_token_is_never_stored_in_clear_text(repository, engine) -> None:
    user = repository.ensure_user(
        telegram_user_id="101",
        telegram_username="user_101",
        display_name="Иван",
        now=NOW,
    )
    token = "SENTINEL-SESSION-TOKEN"
    repository.create_session(
        user_id=user.id,
        token_hash=hash_session_token(token),
        now=NOW,
        expires_at=EXPIRES,
    )

    with engine.connect() as connection:
        stored = connection.execute(text("SELECT token_hash FROM user_sessions")).scalars().all()

    assert token not in stored
    assert stored == [hash_session_token(token)]


def test_project_owner_separates_own_foreign_and_missing(repository, engine) -> None:
    owner = repository.ensure_user(
        telegram_user_id="101", telegram_username="a", display_name="A", now=NOW
    )
    stranger = repository.ensure_user(
        telegram_user_id="202", telegram_username="b", display_name="B", now=NOW
    )
    with engine.begin() as connection:
        for identifier, user_id in ((7, owner.id), (8, stranger.id)):
            connection.execute(
                text(
                    "INSERT INTO content_projects"
                    " (id, name, topic, language, audience, timezone, configuration,"
                    "  owner_id, created_at, updated_at)"
                    " VALUES (:id, 'Проект', '', 'ru', '', 'Europe/Moscow', '{}'::jsonb,"
                    "  :owner_id, :now, :now)"
                ),
                {"id": identifier, "owner_id": user_id, "now": NOW},
            )

    assert repository.project_owner(7) == owner.id
    assert repository.project_owner(8) == stranger.id
    assert repository.project_owner(999) is None


def test_common_prompt_is_empty_until_it_is_written(repository, engine) -> None:
    user = repository.ensure_user(
        telegram_user_id="101", telegram_username="a", display_name="A", now=NOW
    )

    assert repository.common_prompt(user.id) == ""

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO user_settings (user_id, common_prompt, updated_at)"
                " VALUES (:user_id, 'Пиши коротко', :now)"
            ),
            {"user_id": user.id, "now": NOW},
        )

    assert repository.common_prompt(user.id) == "Пиши коротко"
