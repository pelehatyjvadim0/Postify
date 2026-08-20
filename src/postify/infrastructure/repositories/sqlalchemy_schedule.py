from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select, text

from postify.application.scheduling.project_scheduler import (
    ProjectSchedule,
    RouteSchedule,
    ScheduledCommand,
    SourceSchedule,
)
from postify.infrastructure.database.models import (
    ContentProjectModel,
    PublicationRouteModel,
    SourceConnectionModel,
)


class SqlAlchemyScheduleRepository:
    def __init__(
        self,
        session_factory,
        *,
        lock_timeout_ms: int = 1_000,
        statement_timeout_ms: int = 5_000,
    ) -> None:
        if type(lock_timeout_ms) is not int or lock_timeout_ms <= 0:
            raise ValueError("lock_timeout_ms must be positive")
        if type(statement_timeout_ms) is not int or statement_timeout_ms <= 0:
            raise ValueError("statement_timeout_ms must be positive")
        self._session_factory = session_factory
        self._lock_timeout = f"{lock_timeout_ms}ms"
        self._statement_timeout = f"{statement_timeout_ms}ms"

    def list_schedules(self) -> tuple[ProjectSchedule, ...]:
        with self._session_factory() as session:
            self._set_timeouts(session)
            projects = session.execute(
                select(ContentProjectModel.id, ContentProjectModel.timezone).order_by(
                    ContentProjectModel.id
                )
            ).all()
            source_rows = session.execute(
                select(
                    SourceConnectionModel.project_id,
                    SourceConnectionModel.schedule,
                )
                .where(SourceConnectionModel.enabled.is_(True))
                .order_by(SourceConnectionModel.project_id, SourceConnectionModel.id)
            ).all()
            route_rows = session.execute(
                select(
                    PublicationRouteModel.project_id,
                    PublicationRouteModel.id,
                    PublicationRouteModel.schedule,
                )
                .where(PublicationRouteModel.enabled.is_(True))
                .order_by(PublicationRouteModel.project_id, PublicationRouteModel.id)
            ).all()

        sources = defaultdict(list)
        for project_id, cron in source_rows:
            sources[project_id].append(SourceSchedule(enabled=True, cron=cron))
        routes = defaultdict(list)
        for project_id, route_id, schedule in route_rows:
            values = schedule if isinstance(schedule, dict) else {}
            routes[project_id].append(
                RouteSchedule(
                    enabled=True,
                    autopublish=values.get("autopublish") is True,
                    slots=tuple(values.get("slots", ())),
                    route_id=route_id,
                )
            )
        return tuple(
            ProjectSchedule(
                project_id=project_id,
                timezone=timezone,
                sources=tuple(sources[project_id]),
                routes=tuple(routes[project_id]),
            )
            for project_id, timezone in projects
        )

    def claim(self, command: ScheduledCommand) -> bool:
        with self._session_factory() as session:
            try:
                self._set_timeouts(session)
                session.execute(
                    text("SELECT pg_advisory_xact_lock(:project_id)"),
                    {"project_id": command.project_id},
                )
                inserted = session.execute(
                    text(
                        """
                        INSERT INTO schedule_slot_claims
                            (project_id, kind, scheduled_for, route_id)
                        VALUES (:project_id, :kind, :scheduled_for, :route_id)
                        ON CONFLICT DO NOTHING
                        RETURNING true
                        """
                    ),
                    {
                        "project_id": command.project_id,
                        "kind": command.kind,
                        "scheduled_for": command.scheduled_for,
                        "route_id": command.route_id,
                    },
                ).scalar_one_or_none()
                session.commit()
                return inserted is True
            except BaseException:
                session.rollback()
                raise

    def accept(self, command: ScheduledCommand) -> ScheduledCommand | None:
        """Atomically own a route slot, operation run, and recoverable queued job."""
        with self._session_factory() as session:
            try:
                self._set_timeouts(session)
                session.execute(
                    text("SELECT pg_advisory_xact_lock(:project_id)"),
                    {"project_id": command.project_id},
                )
                claimed = session.execute(
                    text(
                        """
                        INSERT INTO schedule_slot_claims
                            (project_id, kind, scheduled_for, route_id)
                        VALUES (:project_id, :kind, :scheduled_for, :route_id)
                        ON CONFLICT DO NOTHING
                        RETURNING true
                        """
                    ),
                    {
                        "project_id": command.project_id,
                        "kind": command.kind,
                        "scheduled_for": command.scheduled_for,
                        "route_id": command.route_id,
                    },
                ).scalar_one_or_none()
                if claimed is not True:
                    session.rollback()
                    return None
                run_id = session.execute(
                    text(
                        """
                        INSERT INTO operation_runs
                            (project_id,operation,status,mode,actor,started_at)
                        VALUES (:project_id,:kind,'running','automatic','scheduler',CURRENT_TIMESTAMP)
                        ON CONFLICT (project_id,operation) WHERE status='running'
                        DO NOTHING RETURNING id
                        """
                    ),
                    {"project_id": command.project_id, "kind": command.kind},
                ).scalar_one_or_none()
                if run_id is None:
                    session.rollback()
                    return None
                job_id = session.execute(
                    text(
                        """
                        INSERT INTO scheduled_jobs
                            (project_id,kind,route_id,scheduled_for,operation_run_id,
                             status,attempt_count,created_at,updated_at)
                        VALUES (:project_id,:kind,:route_id,:scheduled_for,:run_id,
                                'queued',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                        RETURNING id
                        """
                    ),
                    {
                        "project_id": command.project_id,
                        "kind": command.kind,
                        "route_id": command.route_id,
                        "scheduled_for": command.scheduled_for,
                        "run_id": run_id,
                    },
                ).scalar_one()
                session.commit()
                return ScheduledCommand(
                    command.project_id,
                    command.kind,
                    command.scheduled_for,
                    route_id=command.route_id,
                    operation_run_id=run_id,
                    job_id=job_id,
                )
            except BaseException:
                session.rollback()
                raise

    def claim_job(self, job_id: int | None, *, now) -> ScheduledCommand | None:
        if job_id is None:
            return None
        commands = self._claim_jobs(now=now, job_id=job_id)
        return commands[0] if commands else None

    def claim_pending(self, *, now) -> tuple[ScheduledCommand, ...]:
        return self._claim_jobs(now=now)

    def _claim_jobs(
        self, *, now, job_id: int | None = None
    ) -> tuple[ScheduledCommand, ...]:
        with self._session_factory() as session:
            try:
                self._set_timeouts(session)
                job_filter = "" if job_id is None else "AND id=:job_id"
                rows = session.execute(
                    text(
                        f"""
                        SELECT id,project_id,kind,route_id,scheduled_for,operation_run_id
                        FROM scheduled_jobs
                        WHERE true {job_filter}
                          AND (status='queued' OR
                               (status='leased' AND lease_expires_at<=:now))
                        ORDER BY id
                        FOR UPDATE SKIP LOCKED
                        """
                    ),
                    {"job_id": job_id, "now": now},
                ).mappings().all()
                commands = []
                for row in rows:
                    session.execute(
                        text(
                            """
                            UPDATE scheduled_jobs
                            SET status='leased', lease_expires_at=:expires,
                                attempt_count=attempt_count+1, updated_at=:now
                            WHERE id=:id
                            """
                        ),
                        {"id": row.id, "now": now, "expires": now + timedelta(minutes=5)},
                    )
                    commands.append(
                        ScheduledCommand(
                            row.project_id,
                            row.kind,
                            row.scheduled_for,
                            route_id=row.route_id,
                            operation_run_id=row.operation_run_id,
                            job_id=row.id,
                        )
                    )
                session.commit()
                return tuple(commands)
            except BaseException:
                session.rollback()
                raise

    def acknowledge(self, job_id: int, *, succeeded: bool, now) -> None:
        with self._session_factory() as session:
            result = session.execute(
                text(
                    """
                    UPDATE scheduled_jobs
                    SET status=:status, lease_expires_at=NULL, updated_at=:now
                    WHERE id=:id AND status='leased'
                    """
                ),
                {"id": job_id, "status": "succeeded" if succeeded else "failed", "now": now},
            )
            if result.rowcount != 1:
                session.rollback()
                raise RuntimeError("scheduled_job_not_leased")
            session.commit()

    def _set_timeouts(self, session) -> None:
        session.execute(
            text(
                """
                SELECT
                    set_config('lock_timeout', :lock_timeout, true),
                    set_config('statement_timeout', :statement_timeout, true)
                """
            ),
            {
                "lock_timeout": self._lock_timeout,
                "statement_timeout": self._statement_timeout,
            },
        )
