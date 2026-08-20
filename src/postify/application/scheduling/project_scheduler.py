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
    route_id: int | None = None


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
    route_id: int | None = None
    operation_run_id: int | None = None
    job_id: int | None = None


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
        claim_pending = getattr(self._repository, "claim_pending", None)
        if callable(claim_pending):
            for command in claim_pending(now=now.astimezone(UTC)):
                self._run_command(command)
                claimed.append(command)
        for schedule in self._repository.list_schedules():
            local = now.astimezone(ZoneInfo(schedule.timezone))
            commands: list[ScheduledCommand] = []
            if any(
                source.enabled and cron_matches(source.cron, local)
                for source in schedule.sources
            ):
                commands.append(
                    ScheduledCommand(schedule.project_id, "run_once", exact_slot)
                )
            local_slot = local.strftime("%H:%M")
            commands.extend(
                ScheduledCommand(
                    schedule.project_id,
                    "publish_once",
                    exact_slot,
                    route_id=route.route_id,
                )
                for route in schedule.routes
                if route.enabled and route.autopublish and local_slot in route.slots
            )
            for command in commands:
                accept = getattr(self._repository, "accept", None)
                if callable(accept):
                    accepted = accept(command)
                    if accepted is None:
                        continue
                    if isinstance(accepted, ScheduledCommand):
                        command = accepted
                        claim_job = getattr(self._repository, "claim_job", None)
                        if callable(claim_job):
                            leased = claim_job(command.job_id, now=now.astimezone(UTC))
                            if leased is None:
                                continue
                            command = leased
                    else:
                        command = ScheduledCommand(
                            command.project_id,
                            command.kind,
                            command.scheduled_for,
                            route_id=command.route_id,
                            operation_run_id=accepted,
                        )
                elif not self._repository.claim(command):
                    continue
                self._run_command(command)
                claimed.append(command)
        return tuple(claimed)
