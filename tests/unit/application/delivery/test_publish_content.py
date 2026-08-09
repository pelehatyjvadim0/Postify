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

    def reserve_next(self, *, now: datetime):
        package = getattr(self.claim, "package_id", "none")
        self.events.append(f"reserve:{package}")
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
        self.events.append(f"telegram:{claim.package_id}")
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


def test_empty_slot_converts_stale_before_reserving_one_package() -> None:
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

    assert result == Result("published", package_id=41, message_id=731)
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

    assert result == Result(outcome, package_id=41)
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

    assert result == Result("cleanup_completed", package_id=41)
    assert events[-3:] == ["cleanup:find", "delete:/media/41.png", "deleted:11"]
    assert not any(item.startswith(("reserve:", "telegram:")) for item in events)


def test_failed_cleanup_remains_pending_without_telegram_or_failure_attempt() -> None:
    # Поломка: cleanup error отменяет published или записывает delivery attempt.
    _, _, Result, *_ = _api()
    events: list[str] = []

    result = _action(
        RepositoryFake(events, cleanup=approved_claim()),
        PublisherFake(events),
        MediaFake(events, error=OSError("disk")),
    ).execute()

    assert result == Result("cleanup_pending", package_id=41)
    assert not any(item.startswith(("reserve:", "telegram:", "failure:", "deleted:")) for item in events)
