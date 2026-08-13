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
class RouteSchedule:
    enabled: bool
    autopublish: bool
    slots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProjectSchedule:
    project_id: int
    timezone: str
    sources: tuple[SourceSchedule, ...]
    routes: tuple[RouteSchedule, ...]


@dataclass(frozen=True, slots=True)
class ScheduledCommand:
    project_id: int
    kind: Literal["run_once", "publish_once"]
    scheduled_for: datetime
    operation_run_id: int | None = None


class ScheduleRepository(Protocol):
    def list_schedules(self) -> tuple[ProjectSchedule, ...]: ...

    def claim(self, command: ScheduledCommand) -> bool: ...


class ProjectScheduler:
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
        exact_slot = now.astimezone(UTC).replace(second=0, microsecond=0)
        claimed: list[ScheduledCommand] = []
        for schedule in self._repository.list_schedules():
            local = now.astimezone(ZoneInfo(schedule.timezone))
            kinds = []
            if any(
                source.enabled and cron_matches(source.cron, local)
                for source in schedule.sources
            ):
                kinds.append("run_once")
            local_slot = local.strftime("%H:%M")
            if any(
                route.enabled and route.autopublish and local_slot in route.slots
                for route in schedule.routes
            ):
                kinds.append("publish_once")
            for kind in kinds:
                command = ScheduledCommand(schedule.project_id, kind, exact_slot)
                accept = getattr(self._repository, "accept", None)
                if callable(accept):
                    run_id = accept(command)
                    if run_id is None:
                        continue
                    command = ScheduledCommand(
                        command.project_id,
                        command.kind,
                        command.scheduled_for,
                        operation_run_id=run_id,
                    )
                elif not self._repository.claim(command):
                    continue
                self._run_command(command)
                claimed.append(command)
        return tuple(claimed)
