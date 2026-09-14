from __future__ import annotations

import json

from collections.abc import Mapping

from sqlalchemy import text

from postify.domain.observability.models import OperationKind


class InvalidOperationRunTransition(ValueError):
    pass


class SqlAlchemyOperationRunRepository:
    """Журнал длительных операций проекта; UI опрашивает его по operation_id."""

    def __init__(self, session_factory, project_id: int = 1) -> None:
        self.sf = session_factory
        self.project_id = project_id

    def start(self, operation: OperationKind, *, now, mode: str = "automatic", actor: str = "scheduler") -> int:
        with self.sf() as session:
            try:
                # Описания независимы; остальные виды операций по-прежнему
                # допускают только один running на проект.
                run_id = session.execute(text("""
                    INSERT INTO operation_runs(project_id,operation,status,mode,actor,started_at)
                    VALUES (:project,:operation,'running',:mode,:actor,:now)
                    ON CONFLICT (project_id,operation)
                    WHERE status='running' AND operation <> 'caption_media'
                    DO NOTHING RETURNING id
                """), {"project": self.project_id, "operation": OperationKind(operation).value, "mode": mode, "actor": actor, "now": now}).scalar_one_or_none()
                if run_id is None:
                    session.rollback()
                    raise RuntimeError("operation_busy")
                session.commit()
                return run_id
            except BaseException:
                session.rollback()
                raise

    def recover_abandoned_manual(self, *, now) -> int:
        """Вызывается один раз при старте единственного web-процесса.

        У ручных операций нет persistent worker/lease: после остановки
        процесса их исполнителя уже нет. Задачи планировщика восстанавливает
        его собственный механизм, поэтому их состояние здесь не меняется.
        """
        with self.sf() as session, session.begin():
            abandoned = session.execute(text("""
                UPDATE operation_runs
                SET status='failed', failure_code=operation || '_failed',
                    finished_at=:now
                WHERE status='running' AND mode='manual'
                RETURNING project_id, operation
            """), {"now": now}).all()
            for project_id, operation in abandoned:
                if operation in {"generate_post", "regenerate_post"}:
                    session.execute(text("""
                        WITH recovered AS (
                            UPDATE posts p SET status='failed', updated_at=:now
                            WHERE p.project_id=:project AND p.status='generating'
                              AND NOT EXISTS (
                                SELECT 1 FROM scheduled_jobs j
                                JOIN operation_runs r ON r.id=j.operation_run_id
                                LEFT JOIN content_plan_slots s ON s.id=j.slot_id
                                WHERE j.project_id=p.project_id
                                  AND (j.post_id=p.id OR s.post_id=p.id)
                                  AND j.status IN ('queued','leased')
                                  AND r.status='running' AND r.mode='automatic'
                              )
                            RETURNING p.project_id, p.id
                        )
                        INSERT INTO post_status_history
                            (project_id,post_id,status,reason,created_at)
                        SELECT project_id,id,'failed','operation_interrupted',:now
                        FROM recovered
                    """), {"project": project_id, "now": now})
                if operation == "caption_media":
                    session.execute(text("""
                        UPDATE media_assets SET caption_status='failed'
                        WHERE project_id=:project AND caption_status='pending'
                    """), {"project": project_id})
            return len(abandoned)

    def succeed(
        self,
        run_id: int,
        *,
        outcome: str,
        now,
        result: Mapping[str, object] | None = None,
    ) -> None:
        self._finish(run_id, "succeeded", outcome=outcome, now=now, result=result)

    def fail(
        self,
        run_id: int,
        *,
        failure_code: str,
        now,
        result: Mapping[str, object] | None = None,
    ) -> None:
        self._finish(run_id, "failed", failure_code=failure_code, now=now, result=result)

    def _finish(
        self,
        run_id: int,
        status: str,
        *,
        now,
        outcome: str | None = None,
        failure_code: str | None = None,
        result: Mapping[str, object] | None = None,
    ) -> None:
        with self.sf() as session:
            try:
                updated = session.execute(text("""
                    UPDATE operation_runs SET status=:status, outcome=:outcome,
                    failure_code=:failure_code, finished_at=:now,
                    result=CAST(:result AS jsonb)
                    WHERE project_id=:project AND id=:id AND status='running'
                """), {
                    "project": self.project_id,
                    "id": run_id,
                    "status": status,
                    "outcome": outcome,
                    "failure_code": failure_code,
                    "now": now,
                    "result": json.dumps(dict(result or {}), ensure_ascii=False),
                })
                if updated.rowcount != 1:
                    raise InvalidOperationRunTransition("Operation run больше не running")
                session.commit()
            except BaseException:
                session.rollback()
                raise
