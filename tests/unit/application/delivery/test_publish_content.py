from __future__ import annotations
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest


NOW = datetime(2026, 8, 9, 9, tzinfo=UTC)


def _api():
    from postify.application.delivery.publish_content import PublishContent
    from postify.domain.delivery.models import (
        DeliveryClaim,
        PublishContentResult,
        PublishFailureKind,
        TelegramMessage,
        TelegramPublishError,
    )

    return PublishContent, DeliveryClaim, PublishContentResult, PublishFailureKind, TelegramMessage, TelegramPublishError


def approved_claim():
    _, DeliveryClaim, _, _, _, _ = _api()
    return DeliveryClaim(11, 41, 1, "Текст поста", "/media/41.png", "image/png")


@dataclass
class RepositoryFake:
    events: list[str]
    claim: object | None = None
    cleanup: object | None = None
    confirm_error: Exception | None = None

    def mark_stale_sending_uncertain(self, *, stale_before: datetime, now: datetime) -> int:
        self.events.append(f"stale:{stale_before.isoformat()}:{now.isoformat()}")
        return 0

    def pending_cleanup(self):
        self.events.append("cleanup:find")
        return self.cleanup

    def reserve_next(self, *, now: datetime, post_id: int | None = None, delivery_id: int | None = None):
        post = getattr(self.claim, "post_id", "none")
        self.events.append(f"reserve:{post}")
        return self.claim

    def record_failure(self, claim, *, kind, code: str, reason: str, now: datetime) -> None:
        self.events.append(f"failure:{kind.value}:{code}:{reason}:{claim.attempt_no}")

    def confirm_published(self, claim, *, message_id: int, now: datetime) -> None:
        self.events.append(f"commit:{message_id}")
        if self.confirm_error is not None:
            raise self.confirm_error

    def mark_media_deleted(self, delivery_id: int, *, now: datetime) -> None:
        self.events.append(f"deleted:{delivery_id}")


@dataclass
class PublisherFake:
    events: list[str]
    message_id: int = 731
    error: Exception | None = None

    def publish(self, claim):
        self.events.append(f"telegram:{claim.post_id}")
        if self.error is not None:
            raise self.error
        _, _, _, _, TelegramMessage, _ = _api()
        return TelegramMessage(self.message_id)


@dataclass
class MediaFake:
    events: list[str]
    error: Exception | None = None

    def delete(self, path: str) -> None:
        self.events.append(f"delete:{path}")
        if self.error is not None:
            raise self.error


def _action(repository, publisher, media, timeout_seconds: float = 10):
    PublishContent, *_ = _api()
    return PublishContent(
        repository=repository,
        publisher=publisher,
        media=media,
        timeout_seconds=timeout_seconds,
        clock=lambda: NOW,
    )


def test_empty_slot_converts_stale_before_reserving_one_post() -> None:
    # Поломка: stale sending не закрывается до claim или empty вызывает Telegram.
    _, _, Result, *_ = _api()
    events: list[str] = []

    result = _action(RepositoryFake(events), PublisherFake(events), MediaFake(events)).execute()

    assert result == Result("empty")
    assert events == [
        f"stale:{(NOW - timedelta(seconds=10)).isoformat()}:{NOW.isoformat()}",
        "cleanup:find",
        "reserve:none",
    ]


def test_confirmation_is_committed_before_media_delete() -> None:
    # Поломка: медиа удаляется до durable confirmation.
    _, _, Result, *_ = _api()
    events: list[str] = []
    claim = approved_claim()

    result = _action(
        RepositoryFake(events, claim=claim), PublisherFake(events), MediaFake(events)
    ).execute()

    assert result == Result("published", post_id=41, message_id=731)
    assert events[-5:] == [
        "reserve:41",
        "telegram:41",
        "commit:731",
        "delete:/media/41.png",
        "deleted:11",
    ]


def test_failed_confirmation_never_deletes_media_or_reports_published() -> None:
    # Поломка: action удаляет файл/возвращает published после rollback confirmation.
    events: list[str] = []
    repository = RepositoryFake(events, claim=approved_claim(), confirm_error=RuntimeError("db"))

    with pytest.raises(RuntimeError, match="db"):
        _action(repository, PublisherFake(events), MediaFake(events)).execute()

    assert "delete:/media/41.png" not in events
    assert "deleted:11" not in events


@pytest.mark.parametrize("outcome", ["retryable", "failed", "uncertain"])
def test_typed_publish_failure_is_persisted_without_confirmation_or_delete(outcome: str) -> None:
    # Поломка: typed failure теряет класс или переводит пакет в published.
    _, _, Result, FailureKind, _, PublishError = _api()
    events: list[str] = []
    error = PublishError(code="telegram_failure", reason="Безопасная причина", kind=FailureKind(outcome))

    result = _action(
        RepositoryFake(events, claim=approved_claim()),
        PublisherFake(events, error=error),
        MediaFake(events),
    ).execute()

    assert result == Result(outcome, post_id=41)
    assert events[-1] == f"failure:{outcome}:telegram_failure:Безопасная причина:1"
    assert not any(item.startswith(("commit:", "delete:", "deleted:")) for item in events)


def test_pending_cleanup_is_completed_before_claim_without_telegram() -> None:
    # Поломка: cleanup вызывает Telegram или резервирует новый пакет.
    _, _, Result, *_ = _api()
    events: list[str] = []
    cleanup = approved_claim()

    result = _action(
        RepositoryFake(events, claim=approved_claim(), cleanup=cleanup),
        PublisherFake(events),
        MediaFake(events),
    ).execute()

    assert result == Result("cleanup_completed", post_id=41)
    assert events[-3:] == ["cleanup:find", "delete:/media/41.png", "deleted:11"]
    assert not any(item.startswith(("reserve:", "telegram:")) for item in events)


def test_targeted_publish_skips_unrelated_cleanup() -> None:
    # Break caught: publish-now turns into cleanup for an unrelated delivery.
    _, _, Result, *_ = _api()
    events: list[str] = []

    result = _action(
        RepositoryFake(events, claim=approved_claim(), cleanup=approved_claim()),
        PublisherFake(events),
        MediaFake(events),
    ).execute(post_id=41)

    assert result == Result("published", post_id=41, message_id=731)
    assert "cleanup:find" not in events


def test_failed_cleanup_remains_pending_without_telegram_or_failure_attempt() -> None:
    # Поломка: cleanup error отменяет published или записывает delivery attempt.
    _, _, Result, *_ = _api()
    events: list[str] = []

    result = _action(
        RepositoryFake(events, cleanup=approved_claim()),
        PublisherFake(events),
        MediaFake(events, error=OSError("disk")),
    ).execute()

    assert result == Result("cleanup_pending", post_id=41)
    assert not any(item.startswith(("reserve:", "telegram:", "failure:", "deleted:")) for item in events)


@pytest.mark.parametrize("cleanup", [False, True])
def test_real_media_cleanup_error_keeps_publication_pending_without_new_delivery_attempt(
    cleanup: bool,
) -> None:
    # Поломка: ошибка удаления медиа не должна отменять published.
    from postify.application.ports.media_provider import MediaCleanupError

    _, _, Result, *_ = _api()
    events: list[str] = []
    claim = approved_claim()
    result = _action(
        RepositoryFake(events, claim=None if cleanup else claim, cleanup=claim if cleanup else None),
        PublisherFake(events),
        MediaFake(events, error=MediaCleanupError()),
    ).execute()

    assert result == Result("cleanup_pending", post_id=41)
    assert "failure:" not in " ".join(events)
    assert not any(item.startswith("deleted:") for item in events)
    if cleanup:
        assert not any(item.startswith(("reserve:", "telegram:")) for item in events)
    else:
        assert events[-3:] == ["telegram:41", "commit:731", "delete:/media/41.png"]
