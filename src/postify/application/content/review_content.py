from collections.abc import Callable
from datetime import datetime

from postify.application.ports.content_repository import ContentRepository
from postify.application.ports.media_provider import MediaProvider


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

    def approve(self, id):
        return self.r.approve(id, now=self.clock())

    def reject(self, id, *, reason: str = "review"):
        p = self.r.reject(id, now=self.clock(), reason=reason)
        self.m.delete(p.media_path)
        return p
