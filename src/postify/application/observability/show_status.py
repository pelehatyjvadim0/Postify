from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from postify.application.ports.operational_status_repository import (
    OperationalStatusRepository,
)
from postify.domain.observability.models import GroupedState, RawOperationalSnapshot


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    migrations_at_head: bool = True
    postgresql: str = "active"
    import_timer: str = "unknown"
    publish_timer: str = "unknown"
    run_once_service_active: bool = False
    publish_once_service_active: bool = False
    import_timer_last: str | None = None
    import_timer_next: str | None = None
    publish_timer_last: str | None = None
    publish_timer_next: str | None = None
    systemd_failures: tuple[str, ...] = ()
    probe_failed_units: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OperationalSignal:
    severity: str
    code: str
    count: int
    ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class StatusReport:
    snapshot: RawOperationalSnapshot
    day: date
    timezone: str
    daily_target: int
    coverage: int
    deficit: int
    deficit_reasons: tuple[str, ...]
    signals: tuple[OperationalSignal, ...]

    @property
    def candidate_total(self):
        return self.snapshot.candidate_total

    @property
    def candidate_undecided(self):
        return len(self.snapshot.candidate_undecided_ids)

    @property
    def candidate_decisions(self):
        return self.snapshot.candidate_decisions

    @property
    def content_attempts(self):
        return self.snapshot.content_attempts

    @property
    def packages(self):
        return self.snapshot.packages

    @property
    def delivery(self):
        return self.snapshot.delivery

    @property
    def latest_packages(self):
        return self.snapshot.latest_packages

    @property
    def latest_delivery_attempts(self):
        return self.snapshot.latest_delivery_attempts

    @property
    def latest_operation_runs(self):
        return self.snapshot.latest_operation_runs

    @property
    def published_today(self):
        return self.snapshot.published_today

    @property
    def delivery_ready(self):
        return len(self.snapshot.delivery_ready_ids)


def _group(
    snapshot: RawOperationalSnapshot, field: str, code: str
) -> GroupedState | None:
    return next((item for item in getattr(snapshot, field) if item.code == code), None)


class ShowOperationalStatus:
    def __init__(
        self,
        repository: OperationalStatusRepository,
        *,
        timezone: ZoneInfo,
        daily_target: int,
        analysis_limit: int,
        package_limit: int,
        clock: Callable[[], datetime],
    ) -> None:
        self.repository, self.timezone, self.daily_target = (
            repository,
            timezone,
            daily_target,
        )
        self.analysis_limit, self.package_limit, self.clock = (
            analysis_limit,
            package_limit,
            clock,
        )

    def execute(self, runtime: RuntimeSnapshot) -> StatusReport:
        local_now = self.clock().astimezone(self.timezone)
        day = local_now.date()
        start_local = datetime.combine(day, time.min, tzinfo=self.timezone)
        end_local = start_local + timedelta(days=1)
        snapshot = self.repository.snapshot(
            day=day,
            day_start=start_local.astimezone(UTC),
            day_end=end_local.astimezone(UTC),
            limit=10,
        )
        coverage = snapshot.published_today + len(snapshot.delivery_ready_ids)
        deficit = max(self.daily_target - coverage, 0)
        reasons = self._reasons(snapshot, deficit)
        return StatusReport(
            snapshot,
            day,
            str(self.timezone),
            self.daily_target,
            coverage,
            deficit,
            reasons,
            self._signals(snapshot, runtime),
        )

    def _reasons(self, s: RawOperationalSnapshot, deficit: int) -> tuple[str, ...]:
        if not deficit:
            return ("none",)

        def has(field: str, codes: set[str]) -> bool:
            return any(item.code in codes and item.count for item in getattr(s, field))

        reasons: list[str] = []
        if has("delivery", {"failed", "uncertain", "sending"}):
            reasons.append("delivery_blocked")
        if has("packages", {"awaiting_review"}):
            reasons.append("review_backlog")
        if s.daily_packages_created >= self.package_limit:
            reasons.append("package_limit_reached")
        if s.daily_analyses_started >= self.analysis_limit:
            reasons.append("analysis_limit_reached")
        if has("content_attempts", {"retry_scheduled", "failed"}) or has(
            "packages", {"failed"}
        ):
            reasons.append("content_failures")
        if (
            s.selected_without_attempt_ids
            or has("content_attempts", {"processing"})
            or has("packages", {"processing"})
        ):
            reasons.append("processing_backlog")
        if s.candidate_undecided_ids:
            reasons.append("selection_backlog")
        return tuple(reasons or ["eligible_source_shortage"])

    def _signals(
        self, s: RawOperationalSnapshot, runtime: RuntimeSnapshot
    ) -> tuple[OperationalSignal, ...]:
        signals: list[OperationalSignal] = []
        known = {
            "candidate_decisions": {"selected", "rejected"},
            "content_attempts": {
                "processing",
                "retry_scheduled",
                "failed",
                "analyzed_not_selected",
                "packaged",
            },
            "packages": {
                "processing",
                "awaiting_review",
                "approved",
                "rejected",
                "failed",
                "published",
            },
            "delivery": {
                "ready",
                "sending",
                "retryable",
                "failed",
                "uncertain",
                "published",
                "cleanup_pending",
            },
        }
        for field, codes in known.items():
            for item in getattr(s, field):
                if item.code not in codes:
                    signals.append(
                        OperationalSignal(
                            "critical",
                            "unknown_persisted_state",
                            item.count,
                            item.ids[:10],
                        )
                    )

        def add(field: str, code: str, signal: str, severity: str = "warning"):
            item = _group(s, field, code)
            if item and item.count:
                signals.append(
                    OperationalSignal(severity, signal, item.count, item.ids[:10])
                )

        add("delivery", "uncertain", "delivery_uncertain", "critical")
        add("delivery", "failed", "delivery_failed")
        add("delivery", "retryable", "delivery_retryable")
        if s.pending_cleanup_ids:
            signals.append(
                OperationalSignal(
                    "warning",
                    "media_cleanup_pending",
                    len(s.pending_cleanup_ids),
                    s.pending_cleanup_ids[:10],
                )
            )
        add("content_attempts", "failed", "content_attempt_failed")
        add("packages", "failed", "content_package_failed")
        add("packages", "awaiting_review", "review_required")
        for run in s.latest_operation_runs:
            if run.status == "failed":
                signals.append(
                    OperationalSignal("warning", "operation_failed", 1, (run.run_id,))
                )
            active = (
                runtime.run_once_service_active
                if run.operation == "run_once"
                else runtime.publish_once_service_active
            )
            if run.status == "running" and not active:
                signals.append(
                    OperationalSignal(
                        "warning", "operation_unfinished", 1, (run.run_id,)
                    )
                )
        if not runtime.migrations_at_head:
            signals.append(OperationalSignal("critical", "migration_not_at_head", 1))
        failures = runtime.systemd_failures or runtime.probe_failed_units
        if failures:
            signals.append(
                OperationalSignal("warning", "systemd_probe_failed", len(failures))
            )
        return tuple(signals)
