from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from postify.domain.projects.cron import cron_matches


@dataclass(frozen=True, slots=True)
class SourceSchedule:
    enabled: bool
    cron: str


@dataclass(frozen=True, slots=True)
class ProjectSchedule:
    project_id: int
    timezone: str
    sources: tuple[SourceSchedule, ...]


@dataclass(frozen=True, slots=True)
class ScheduledCommand:
    project_id: int
    kind: Literal["run_once", "publish_once"]
    scheduled_for: datetime
    route_id: int | None = None
    operation_run_id: int | None = None
    job_id: int | None = None
    package_id: int | None = None


class ScheduleRepository(Protocol):
    def list_schedules(self) -> tuple[ProjectSchedule, ...]: ...
    def due_publications(self, *, project_id: int, now: datetime) -> tuple[ScheduledCommand, ...]: ...
    def recover_stale_deliveries(self, *, now: datetime) -> int: ...
    def claim_pending(self, *, now: datetime) -> tuple[ScheduledCommand, ...]: ...
    def accept(self, command: ScheduledCommand) -> ScheduledCommand | None: ...
    def claim_job(self, job_id: int | None, *, now: datetime) -> ScheduledCommand | None: ...


class ProjectScheduler:
    def __init__(self, repository: ScheduleRepository, run_command: Callable[[ScheduledCommand], object]) -> None:
        self._repository = repository
        self._run_command = run_command

    def tick(self, now: datetime) -> tuple[ScheduledCommand, ...]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must contain timezone")
        utc_now = now.astimezone(UTC)
        exact_slot = utc_now.replace(second=0, microsecond=0)
        claimed: list[ScheduledCommand] = []
        self._repository.recover_stale_deliveries(now=utc_now)
        for command in self._repository.claim_pending(now=utc_now):
            self._run_command(command)
            claimed.append(command)
        for schedule in self._repository.list_schedules():
            local = now.astimezone(ZoneInfo(schedule.timezone))
            commands = list(self._repository.due_publications(project_id=schedule.project_id, now=utc_now))
            if any(source.enabled and cron_matches(source.cron, local) for source in schedule.sources):
                commands.append(ScheduledCommand(schedule.project_id, "run_once", exact_slot))
            for command in commands:
                accepted = self._repository.accept(command)
                if accepted is None:
                    continue
                leased = self._repository.claim_job(accepted.job_id, now=utc_now)
                if leased is None:
                    continue
                self._run_command(leased)
                claimed.append(leased)
        return tuple(claimed)
