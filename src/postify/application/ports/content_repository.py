from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from dataclasses import dataclass
from typing import Protocol

from postify.domain.content.models import (
    BatchAnalysis,
    ContentAttempt,
    ExecutionContext,
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
    def attempt_status(self, attempt_id: int) -> str | None: ...


    def claim(
        self, *, now: datetime, batch_size: int,
        context: ExecutionContext = ...
    ) -> Sequence[ContentAttempt]: ...
    def fail_attempt(self, attempt_id: int, *, code: str, now: datetime) -> None: ...
    def save_extracted(self, attempt_id: int, article: ExtractedArticle) -> None: ...
    def save_analysis_and_create_packages(
        self,
        batch: BatchAnalysis,
        *,
        articles: Mapping[int, ExtractedArticle],
        generation_snapshot: Mapping[str, object],
        now: datetime,
        context: ExecutionContext = ...,
    ) -> Sequence[PackageDraft]: ...
    def complete_package(
        self, package_id: int, *, media: StoredMedia | None, status: str, now: datetime
    ) -> None: ...
    def fail_package(self, package_id: int, *, code: str, now: datetime) -> None: ...
    def active_media_paths(self) -> set[str]: ...
    def list_packages(self) -> Sequence[ContentPackage]: ...
    def get_package(self, package_id: int) -> ContentPackage: ...
    def save_plan(
        self, package_id: int, *, scheduled_at: datetime, route_id: int, now: datetime
    ) -> ContentPackage: ...
    def approve(self, package_id: int, *, now: datetime) -> ContentPackage: ...
    def reject(
        self, package_id: int, *, now: datetime, reason: str | None = None
    ) -> ContentPackage: ...
