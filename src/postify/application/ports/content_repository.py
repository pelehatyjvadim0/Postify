from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from dataclasses import dataclass
from typing import Protocol

from postify.domain.content.models import (
    BatchAnalysis,
    ContentAttempt,
    ContentLimits,
    ContentPackage,
    ExtractedArticle,
    StoredMedia,
)


@dataclass(frozen=True, slots=True)
class PackageDraft:
    attempt_id: int
    package_id: int
    article: ExtractedArticle
    media_query: str


class ContentRepository(Protocol):
    def claim(
        self, *, now: datetime, day: date, limits: ContentLimits
    ) -> Sequence[ContentAttempt]: ...
    def schedule_article_retry(
        self, attempt_id: int, *, retry_at: datetime, now: datetime
    ) -> None: ...
    def fail_attempt(self, attempt_id: int, *, code: str, now: datetime) -> None: ...
    def save_extracted(self, attempt_id: int, article: ExtractedArticle) -> None: ...
    def package_slots_remaining(self, *, day: date, limit: int) -> int: ...
    def save_analysis_and_create_packages(
        self,
        batch: BatchAnalysis,
        *,
        articles: Mapping[int, ExtractedArticle],
        review_required: bool,
        now: datetime,
        day: date,
        package_limit: int,
    ) -> Sequence[PackageDraft]: ...
    def complete_package(
        self, package_id: int, *, media: StoredMedia, status: str, now: datetime
    ) -> None: ...
    def fail_package(self, package_id: int, *, code: str, now: datetime) -> None: ...
    def active_media_paths(self) -> set[str]: ...
    def list_packages(self) -> Sequence[ContentPackage]: ...
    def get_package(self, package_id: int) -> ContentPackage: ...
    def approve(self, package_id: int, *, now: datetime) -> ContentPackage: ...
    def reject(
        self, package_id: int, *, now: datetime, reason: str = "review"
    ) -> ContentPackage: ...
