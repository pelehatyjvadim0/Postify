from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from postify.domain.posts.models import Post, StoredMedia


class PostRepository(Protocol):
    """Хранилище постов: чтение, редакторские решения, план публикации."""

    def list_posts(self) -> Sequence[Post]: ...

    def get_post(self, post_id: int) -> Post: ...

    def save_plan(
        self, post_id: int, *, scheduled_at: datetime, now: datetime
    ) -> Post: ...

    def approve(self, post_id: int, *, now: datetime) -> Post: ...

    def reject(
        self, post_id: int, *, now: datetime, reason: str | None = None
    ) -> Post: ...

    def attach_media(
        self, post_id: int, *, media: StoredMedia | None, now: datetime
    ) -> Post: ...

    def active_media_paths(self) -> set[str]: ...
