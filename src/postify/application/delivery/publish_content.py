from __future__ import annotations

from datetime import timedelta

from postify.domain.delivery.models import PublishContentResult, TelegramPublishError
from postify.application.ports.media_provider import MediaCleanupError


class PublishContent:
    def __init__(self, repository, publisher, media, *, timeout_seconds: float, clock) -> None:
        self.repository = repository
        self.publisher = publisher
        self.media = media
        self.timeout_seconds = timeout_seconds
        self.clock = clock

    def execute(self, *, post_id: int | None = None, delivery_id: int | None = None) -> PublishContentResult:
        now = self.clock()
        self.repository.mark_stale_sending_uncertain(
            stale_before=now - timedelta(seconds=self.timeout_seconds), now=now
        )
        if post_id is None and delivery_id is None:
            cleanup = self.repository.pending_cleanup()
            if cleanup is not None:
                try:
                    if cleanup.media_path:
                        self.media.delete(cleanup.media_path)
                except (OSError, MediaCleanupError):
                    return PublishContentResult("cleanup_pending", post_id=cleanup.post_id)
                self.repository.mark_media_deleted(cleanup.delivery_id, now=now)
                return PublishContentResult("cleanup_completed", post_id=cleanup.post_id)
        claim = (
            self.repository.reserve_next(now=now)
            if post_id is None and delivery_id is None
            else self.repository.reserve_next(
                now=now, post_id=post_id, delivery_id=delivery_id
            )
        )
        if claim is None:
            return PublishContentResult("empty")
        try:
            message = self.publisher.publish(claim)
        except TelegramPublishError as error:
            self.repository.record_failure(claim, kind=error.kind, code=error.code, reason=error.reason, now=now)
            return PublishContentResult(error.kind.value, post_id=claim.post_id)
        self.repository.confirm_published(claim, message_id=message.message_id, now=now)
        try:
            if claim.media_path:
                self.media.delete(claim.media_path)
        except (OSError, MediaCleanupError):
            return PublishContentResult("cleanup_pending", post_id=claim.post_id)
        self.repository.mark_media_deleted(claim.delivery_id, now=now)
        return PublishContentResult("published", post_id=claim.post_id, message_id=message.message_id)
