from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class ProjectSchedule:
    project_id: int
    timezone: str


@dataclass(frozen=True, slots=True)
class ScheduledCommand:
    project_id: int
    kind: Literal["generate_post", "publish_once"]
    scheduled_for: datetime
    post_id: int | None = None
    operation_run_id: int | None = None
    job_id: int | None = None


class ScheduleRepository(Protocol):
    def list_schedules(self) -> tuple[ProjectSchedule, ...]: ...
    def due_publications(
        self, *, project_id: int, now: datetime
    ) -> tuple[ScheduledCommand, ...]: ...
    def recover_stale_deliveries(self, *, now: datetime) -> int: ...
    def claim_pending(self, *, now: datetime) -> tuple[ScheduledCommand, ...]: ...
    def accept(self, command: ScheduledCommand) -> ScheduledCommand | None: ...
    def claim_job(
        self, job_id: int | None, *, now: datetime
    ) -> ScheduledCommand | None: ...


class ProjectScheduler:
    """Один тик: восстановление, отложенные задачи, публикации по плану.

    Постановка генерации по ``generate_at`` добавляется треком контент-плана —
    для неё достаточно вернуть команды ``generate_post`` из репозитория.
    """

    def __init__(
        self,
        repository: ScheduleRepository,
        run_command: Callable[[ScheduledCommand], object],
    ) -> None:
        self._repository = repository
        self._run_command = run_command

    def tick(self, now: datetime) -> tuple[ScheduledCommand, ...]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must contain timezone")
        utc_now = now.astimezone(UTC)
        claimed: list[ScheduledCommand] = []
        self._repository.recover_stale_deliveries(now=utc_now)
        for command in self._repository.claim_pending(now=utc_now):
            self._run_command(command)
            claimed.append(command)
        for schedule in self._repository.list_schedules():
            for command in self._repository.due_publications(
                project_id=schedule.project_id, now=utc_now
            ):
                accepted = self._repository.accept(command)
                if accepted is None:
                    continue
                leased = self._repository.claim_job(accepted.job_id, now=utc_now)
                if leased is None:
                    continue
                self._run_command(leased)
                claimed.append(leased)
        return tuple(claimed)
