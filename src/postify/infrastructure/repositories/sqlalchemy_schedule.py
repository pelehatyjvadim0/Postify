from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, text

from postify.application.scheduling.project_scheduler import (
    ProjectSchedule,
    ScheduledCommand,
)
from postify.infrastructure.database.models import ContentProjectModel

_PRE_DELIVERY_RETRY_DELAY = timedelta(minutes=1)


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
        return tuple(
            ProjectSchedule(project_id=project_id, timezone=timezone)
            for project_id, timezone in projects
        )

    def recover_stale_deliveries(self, *, now) -> int:
        from postify.infrastructure.repositories.sqlalchemy_delivery import SqlAlchemyDeliveryRepository
        with self._session_factory() as session:
            projects = session.execute(text("""
                SELECT p.id,COALESCE((p.configuration->>'analysis_timeout_seconds')::int,60) AS timeout
                FROM content_projects p WHERE EXISTS (
                    SELECT 1 FROM deliveries d WHERE d.project_id=p.id AND d.status='sending'
                    AND d.sending_started_at < :now - make_interval(secs => COALESCE((p.configuration->>'analysis_timeout_seconds')::int,60)))
            """), {"now": now}).all()
        return sum(SqlAlchemyDeliveryRepository(self._session_factory, project.id).mark_stale_sending_uncertain(
            stale_before=now - timedelta(seconds=project.timeout), now=now) for project in projects)

    def due_publications(self, *, project_id, now) -> tuple[ScheduledCommand, ...]:
        with self._session_factory() as session:
            self._set_timeouts(session)
            rows = session.execute(text("""
                SELECT p.id,s.publish_at FROM posts p
                JOIN content_plan_slots s ON s.project_id=p.project_id
                                         AND s.post_id=p.id
                JOIN channel_connections c ON c.project_id=p.project_id
                WHERE p.project_id=:project AND p.status='approved'
                  AND s.status<>'skipped' AND s.publish_at<=:now AND c.enabled
                    AND NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.project_id=p.project_id
                    AND d.post_id=p.id AND d.status IN ('sending','published','uncertain','failed'))
                ORDER BY s.publish_at,p.id
            """), {"project": project_id, "now": now}).all()
            return tuple(
                ScheduledCommand(project_id, "publish_once", row.publish_at, post_id=row.id)
                for row in rows
            )

    def due_generations(self, *, project_id, now) -> tuple[ScheduledCommand, ...]:
        """Слоты плана, которым пора генерировать.

        Выборка живёт в репозитории плана: условие «пора генерировать» одно на
        весь проект, и раздваивать его между двумя SQL нельзя.
        """
        from postify.infrastructure.repositories.sqlalchemy_plan import (
            SqlAlchemyPlanRepository,
        )

        slots = SqlAlchemyPlanRepository(
            self._session_factory, project_id
        ).due_generations(now=now)
        return tuple(
            ScheduledCommand(
                project_id, "generate_post", slot.generate_at, slot_id=slot.id
            )
            for slot in slots
        )

    def accept(self, command: ScheduledCommand) -> ScheduledCommand | None:
        """Atomically own a route slot, operation run, and recoverable queued job."""
        if command.kind == "publish_once" and command.post_id is None:
            return None
        if command.kind == "generate_post" and command.slot_id is None:
            return None
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
                            (project_id, kind, scheduled_for, post_id, slot_id)
                        VALUES (:project_id, :kind, :scheduled_for, :post_id, :slot_id)
                        ON CONFLICT DO NOTHING
                        RETURNING true
                        """
                    ),
                    {
                        "project_id": command.project_id,
                        "kind": command.kind,
                        "scheduled_for": command.scheduled_for,
                        "post_id": command.post_id,
                        "slot_id": command.slot_id,
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
                            (project_id,kind,post_id,slot_id,scheduled_for,
                             operation_run_id,status,attempt_count,created_at,updated_at)
                        VALUES (:project_id,:kind,:post_id,:slot_id,:scheduled_for,
                                :run_id,'queued',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                        RETURNING id
                        """
                    ),
                    {
                        "project_id": command.project_id,
                        "kind": command.kind,
                        "post_id": command.post_id,
                        "slot_id": command.slot_id,
                        "scheduled_for": command.scheduled_for,
                        "run_id": run_id,
                    },
                ).scalar_one()
                session.commit()
                return ScheduledCommand(
                    command.project_id,
                    command.kind,
                    command.scheduled_for,
                    post_id=command.post_id,
                    slot_id=command.slot_id,
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
                        SELECT id,project_id,kind,post_id,slot_id,scheduled_for,
                               operation_run_id,status
                        FROM scheduled_jobs
                        WHERE true {job_filter}
                          AND (status='queued' OR
                               (status='leased' AND lease_expires_at<=:now) OR
                               (status='failed' AND kind='publish_once'
                                AND post_id IS NOT NULL
                                AND updated_at<=:failed_before
                                AND NOT EXISTS (
                                    SELECT 1 FROM deliveries d
                                    WHERE d.project_id=scheduled_jobs.project_id
                                      AND d.post_id=scheduled_jobs.post_id
                                )))
                        ORDER BY id
                        FOR UPDATE SKIP LOCKED
                        """
                    ),
                    {
                        "job_id": job_id,
                        "now": now,
                        "failed_before": now - _PRE_DELIVERY_RETRY_DELAY,
                    },
                ).mappings().all()
                commands = []
                for row in rows:
                    # Задача без цели невыполнима: гасим её вместе с операцией,
                    # иначе UI будет вечно опрашивать running.
                    if (row.kind == "publish_once" and row.post_id is None) or (
                        row.kind == "generate_post" and row.slot_id is None
                    ):
                        session.execute(text("UPDATE scheduled_jobs SET status='failed',lease_expires_at=NULL,updated_at=:now WHERE id=:id"), {"id": row.id, "now": now})
                        session.execute(text("UPDATE operation_runs SET status='failed',failure_code=:code,finished_at=:now WHERE id=:id AND status='running'"), {"id": row.operation_run_id, "code": f"{row.kind}_failed", "now": now})
                        continue
                    operation_run_id = row.operation_run_id
                    if row.status == "failed":
                        session.execute(
                            text(
                                "UPDATE operation_runs SET status='failed',"
                                "failure_code=COALESCE(failure_code,'publish_once_failed'),"
                                "finished_at=COALESCE(finished_at,:now) "
                                "WHERE id=:id AND status='running'"
                            ),
                            {"id": row.operation_run_id, "now": now},
                        )
                        operation_run_id = session.execute(
                            text(
                                "INSERT INTO operation_runs"
                                "(project_id,operation,status,mode,actor,started_at) "
                                "SELECT :project,'publish_once','running','automatic','scheduler',:now "
                                "WHERE NOT EXISTS ("
                                "SELECT 1 FROM operation_runs "
                                "WHERE project_id=:project AND status='running') "
                                "ON CONFLICT (project_id,operation) WHERE status='running' "
                                "DO NOTHING RETURNING id"
                            ),
                            {"project": row.project_id, "now": now},
                        ).scalar_one_or_none()
                        if operation_run_id is None:
                            continue
                    session.execute(
                        text(
                            """
                            UPDATE scheduled_jobs
                            SET status='leased', operation_run_id=:operation_run_id,
                                lease_expires_at=:expires, attempt_count=attempt_count+1,
                                updated_at=:now
                            WHERE id=:id
                            """
                        ),
                        {
                            "id": row.id,
                            "operation_run_id": operation_run_id,
                            "now": now,
                            "expires": now + timedelta(minutes=5),
                        },
                    )
                    commands.append(
                        ScheduledCommand(
                            row.project_id,
                            row.kind,
                            row.scheduled_for,
                            post_id=row.post_id,
                            slot_id=row.slot_id,
                            operation_run_id=operation_run_id,
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
