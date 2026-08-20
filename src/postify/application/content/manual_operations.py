from __future__ import annotations

from dataclasses import dataclass

from postify.application.ports.content_repository import ContentRepository
from postify.domain.content.models import (
    ExecutionActor,
    ExecutionContext,
    ExecutionMode,
    ExecutionPurpose,
    InvalidContentTransition,
)


class ReviewUnresolved(InvalidContentTransition):
    def __init__(self, package_ids: tuple[int, ...]) -> None:
        super().__init__("review_unresolved")
        self.package_ids = package_ids


@dataclass(frozen=True, slots=True)
class ManualContentOperations:
    """Validate owner commands and produce server-owned execution contexts."""

    repository: ContentRepository

    def load_more(self) -> ExecutionContext:
        unresolved = tuple(self.repository.awaiting_review_package_ids(limit=50))
        if unresolved:
            raise ReviewUnresolved(unresolved)
        return ExecutionContext(
            mode=ExecutionMode.MANUAL,
            actor=ExecutionActor.UI,
            purpose=ExecutionPurpose.LOAD_MORE,
            batch_size=3,
        )

    def retry_analysis(self, attempt_id: int) -> ExecutionContext:
        status = self.repository.attempt_status(attempt_id)
        if status is None:
            raise LookupError(attempt_id)
        if status not in {"failed", "retry_scheduled"}:
            raise InvalidContentTransition("invalid_transition")
        return ExecutionContext(
            mode=ExecutionMode.MANUAL,
            actor=ExecutionActor.UI,
            purpose=ExecutionPurpose.RETRY_ANALYSIS,
            batch_size=1,
            target_attempt_id=attempt_id,
        )

    def return_to_analysis(self, package_id: int) -> ExecutionContext:
        return self._package_context(
            package_id,
            purpose=ExecutionPurpose.RETURN_TO_ANALYSIS,
            allowed={"rejected"},
            batch_size=1,
        )

    def regenerate_post(self, package_id: int) -> ExecutionContext:
        return self._package_context(
            package_id,
            purpose=ExecutionPurpose.REGENERATE_POST,
            allowed={"awaiting_review", "rejected", "approved"},
            batch_size=1,
        )

    def replace_media(self, package_id: int) -> ExecutionContext:
        return self._package_context(
            package_id,
            purpose=ExecutionPurpose.REPLACE_MEDIA,
            allowed={"awaiting_review", "rejected", "approved"},
        )

    def publish_now(self, package_id: int) -> ExecutionContext:
        return self._package_context(
            package_id,
            purpose=ExecutionPurpose.PUBLISH_NOW,
            allowed={"approved"},
        )

    def _package_context(
        self,
        package_id: int,
        *,
        purpose: ExecutionPurpose,
        allowed: set[str],
        batch_size: int | None = None,
    ) -> ExecutionContext:
        package = self.repository.get_package(package_id)
        if str(package.status) not in allowed:
            raise InvalidContentTransition("invalid_transition")
        return ExecutionContext(
            mode=ExecutionMode.MANUAL,
            actor=ExecutionActor.UI,
            purpose=purpose,
            batch_size=batch_size,
            target_package_id=package_id,
        )
