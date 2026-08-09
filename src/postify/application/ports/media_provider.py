from __future__ import annotations

from datetime import datetime
from typing import Protocol

from postify.domain.content.models import ExtractedArticle, StoredMedia


class MediaCleanupError(RuntimeError):
    """Локальное медиа не удалось удалить; confirmed delivery остаётся pending cleanup."""


class MediaProvider(Protocol):
    def acquire(self, article: ExtractedArticle, query: str) -> StoredMedia: ...

    def delete(self, local_path: str) -> None: ...

    def cleanup(self, *, older_than: datetime, protected_paths: set[str]) -> int: ...
