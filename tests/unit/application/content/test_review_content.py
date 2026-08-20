from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest


NOW = datetime(2026, 8, 8, 14, tzinfo=UTC)


def _api():
    from postify.application.content.review_content import ReviewContent
    from postify.domain.content.models import InvalidContentTransition

    return ReviewContent, InvalidContentTransition


class ReviewRepository:
    def __init__(self, package: object) -> None:
        self.package = package
        self.events: list[tuple[object, ...]] = []

    def list_packages(self):
        return (self.package,)

    def get_package(self, package_id: int):
        assert package_id == self.package.id
        return self.package

    def approve(self, package_id: int, *, now: datetime):
        self.events.append(("approve", package_id, now))
        if self.package.status != "awaiting_review":
            _, InvalidContentTransition = _api()
            raise InvalidContentTransition("invalid")
        self.package.status = "approved"
        self.package.history.append(("approved", now))
        return self.package

    def reject(self, package_id: int, *, now: datetime, reason: str | None = None):
        self.events.append(("reject", package_id, now, reason))
        if self.package.status != "awaiting_review":
            _, InvalidContentTransition = _api()
            raise InvalidContentTransition("invalid")
        self.package.status = "rejected"
        self.package.history.append(("rejected", now))
        return self.package


class DeletingMedia:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.deleted: list[str] = []

    def delete(self, local_path: str) -> None:
        self.deleted.append(local_path)
        if self.error is not None:
            raise self.error


def _package(status: str = "awaiting_review"):
    return SimpleNamespace(
        id=7,
        source_url="https://source.test/article",
        context="ARTICLE-BODY complete context",
        analysis="Полезный анализ",
        post_text="Текст поста",
        media_path="/media/7.jpg",
        media_source_type="og",
        media_source_url="https://cdn.test/7.jpg",
        status=status,
        history=[("not_started", NOW), ("processing", NOW), (status, NOW)],
    )


def test_approve_changes_database_history_without_deleting_media() -> None:
    # Поломка (gate 6/9): approve не атомарен или удаляет активное медиа до Telegram.
    ReviewContent, _ = _api()
    repository = ReviewRepository(_package())
    media = DeletingMedia()

    result = ReviewContent(repository, media, clock=lambda: NOW).approve(7)

    assert result.status == "approved"
    assert result.history[-1] == ("approved", NOW)
    assert media.deleted == []


def test_reject_commits_status_before_media_delete() -> None:
    # Поломка (gate 9): delete выполняется до фиксации rejected.
    ReviewContent, _ = _api()
    package = _package()
    repository = ReviewRepository(package)

    class OrderedMedia(DeletingMedia):
        def delete(self, local_path: str) -> None:
            assert package.status == "rejected"
            super().delete(local_path)

    media = OrderedMedia()

    result = ReviewContent(repository, media, clock=lambda: NOW).reject(7)

    assert result.status == "rejected"
    assert media.deleted == ["/media/7.jpg"]


def test_reject_records_no_user_reason_in_history() -> None:
    # Break caught: package rejection records untrusted feedback from the UI.
    ReviewContent, _ = _api()
    package = _package()
    repository = ReviewRepository(package)

    ReviewContent(repository, DeletingMedia(), clock=lambda: NOW).reject(7)

    assert repository.events == [("reject", 7, NOW, None)]


def test_failed_reject_delete_keeps_rejected_package_recoverable() -> None:
    # Поломка (gate 9/10): delete-сбой откатывает DB-статус или скрывает path от cleanup.
    ReviewContent, _ = _api()
    package = _package()
    repository = ReviewRepository(package)
    media = DeletingMedia(OSError("disk unavailable"))

    with pytest.raises(OSError, match="disk unavailable"):
        ReviewContent(repository, media, clock=lambda: NOW).reject(7)

    assert package.status == "rejected"
    assert package.media_path == "/media/7.jpg"
    assert package.history[-1] == ("rejected", NOW)


@pytest.mark.parametrize("operation", ["approve", "reject"])
def test_invalid_review_transition_changes_neither_history_nor_media(operation: str) -> None:
    # Поломка (gate 6): repeated/terminal review добавляет history или удаляет файл.
    ReviewContent, InvalidContentTransition = _api()
    package = _package(status="approved")
    before = list(package.history)
    repository = ReviewRepository(package)
    media = DeletingMedia()
    review = ReviewContent(repository, media, clock=lambda: NOW)

    with pytest.raises(InvalidContentTransition):
        getattr(review, operation)(7)

    assert package.status == "approved"
    assert package.history == before
    assert media.deleted == []
