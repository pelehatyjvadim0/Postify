from collections.abc import Callable
from datetime import datetime

from postify.application.ports.content_repository import ContentRepository
from postify.application.ports.media_provider import MediaCleanupError, MediaProvider


class ReviewContent:
    def __init__(
        self,
        repository: ContentRepository,
        media: MediaProvider,
        *,
        clock: Callable[[], datetime],
    ):
        self.r = repository
        self.m = media
        self.clock = clock

    def list(self):
        return self.r.list_packages()

    def show(self, id):
        return self.r.get_package(id)

    def save_plan(self, id, *, scheduled_at, route_id):
        return self.r.save_plan(id, scheduled_at=scheduled_at, route_id=route_id, now=self.clock())

    def approve(self, id):
        return self.r.approve(id, now=self.clock())

    def reject(self, id):
        p = self.r.reject(id, now=self.clock(), reason=None)
        if p.media_path:
            try:
                self.m.delete(p.media_path)
            except MediaCleanupError:
                # The editorial decision is already committed. Stale media is
                # safe to leave for the regular unprotected-file cleanup.
                pass
        return p
