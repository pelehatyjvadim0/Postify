from __future__ import annotations

from sqlalchemy import text

from postify.domain.observability.models import OperationKind


class InvalidOperationRunTransition(ValueError):
    pass


class SqlAlchemyOperationRunRepository:
    def __init__(self, session_factory, project_id: int = 1) -> None:
        self.sf = session_factory
        self.project_id = project_id

    def start(self, operation: OperationKind, *, now, mode: str = "automatic", actor: str = "scheduler") -> int:
        with self.sf() as session:
            try:
                run_id = session.execute(text("""
                    INSERT INTO operation_runs(project_id,operation,status,mode,actor,started_at)
                    VALUES (:project,:operation,'running',:mode,:actor,:now)
                    ON CONFLICT (project_id,operation) WHERE status='running'
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

    def succeed(self, run_id: int, *, outcome: str, now, **metadata) -> None:
        self._finish(run_id, "succeeded", outcome=outcome, now=now, **metadata)

    def fail(self, run_id: int, *, failure_code: str, now, **metadata) -> None:
        self._finish(run_id, "failed", failure_code=failure_code, now=now, **metadata)

    def _finish(self, run_id: int, status: str, *, now, outcome: str | None = None, failure_code: str | None = None, codex_model: str | None = None, codex_reasoning_effort: str | None = None, materials_taken: int = 0, packages_created: int = 0) -> None:
        with self.sf() as session:
            try:
                result = session.execute(text("""
                    UPDATE operation_runs SET status=:status, outcome=:outcome,
                    failure_code=:failure_code, finished_at=:now,
                    codex_model=:codex_model,
                    codex_reasoning_effort=:codex_reasoning_effort,
                    materials_taken=:materials_taken,
                    packages_created=:packages_created
                    WHERE project_id=:project AND id=:id AND status='running'
                """), {"project": self.project_id, "id": run_id, "status": status, "outcome": outcome, "failure_code": failure_code, "now": now, "codex_model": codex_model, "codex_reasoning_effort": codex_reasoning_effort, "materials_taken": materials_taken, "packages_created": packages_created})
                if result.rowcount != 1:
                    raise InvalidOperationRunTransition("Operation run больше не running")
                session.commit()
            except BaseException:
                session.rollback()
                raise
