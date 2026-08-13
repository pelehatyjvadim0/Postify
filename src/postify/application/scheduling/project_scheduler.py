from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from zoneinfo import ZoneInfo


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
                source.enabled and _cron_matches(source.cron, local)
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
                if self._repository.claim(command):
                    self._run_command(command)
                    claimed.append(command)
        return tuple(claimed)


def _cron_matches(expression: str, local: datetime) -> bool:
    fields = expression.split()
    if len(fields) != 5:
        return False
    minute, hour, day, month, weekday = fields
    cron_weekday = (local.weekday() + 1) % 7
    if not all(
        (
            _field_matches(minute, local.minute, 0, 59),
            _field_matches(hour, local.hour, 0, 23),
            _field_matches(month, local.month, 1, 12),
        )
    ):
        return False
    day_matches = _field_matches(day, local.day, 1, 31)
    weekday_matches = _field_matches(weekday, cron_weekday, 0, 7, sunday=True)
    if day == "*":
        return weekday_matches
    if weekday == "*":
        return day_matches
    return day_matches or weekday_matches


def _field_matches(
    field: str,
    value: int,
    minimum: int,
    maximum: int,
    *,
    sunday: bool = False,
) -> bool:
    try:
        return any(
            _part_matches(part, value, minimum, maximum, sunday=sunday)
            for part in field.split(",")
        )
    except (TypeError, ValueError, ZeroDivisionError):
        return False


def _part_matches(
    part: str,
    value: int,
    minimum: int,
    maximum: int,
    *,
    sunday: bool,
) -> bool:
    base, separator, step_text = part.partition("/")
    step = int(step_text) if separator else 1
    if step <= 0:
        return False
    if base == "*":
        start, end = minimum, maximum
    elif "-" in base:
        start_text, end_text = base.split("-", 1)
        start, end = int(start_text), int(end_text)
    else:
        start = end = int(base)
    if not minimum <= start <= end <= maximum:
        return False
    comparable = 7 if sunday and value == 0 and start == 7 else value
    return start <= comparable <= end and (comparable - start) % step == 0
