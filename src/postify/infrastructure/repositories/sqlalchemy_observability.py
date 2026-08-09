from __future__ import annotations

from sqlalchemy import text

from postify.domain.observability.models import (
    DeliveryAttemptSummary,
    GroupedState,
    OperationKind,
    OperationRunSummary,
    PackageSummary,
    RawOperationalSnapshot,
)


class InvalidOperationRunTransition(ValueError):
    pass


class SqlAlchemyOperationRunRepository:
    def __init__(self, session_factory) -> None:
        self.sf = session_factory

    def start(self, operation: OperationKind, *, now) -> int:
        with self.sf() as session:
            try:
                run_id = session.execute(text("""
                    INSERT INTO operation_runs(operation,status,started_at)
                    VALUES (:operation,'running',:now) RETURNING id
                """), {"operation": OperationKind(operation).value, "now": now}).scalar_one()
                session.commit()
                return run_id
            except BaseException:
                session.rollback()
                raise

    def succeed(self, run_id: int, *, outcome: str, now) -> None:
        self._finish(run_id, "succeeded", outcome=outcome, now=now)

    def fail(self, run_id: int, *, failure_code: str, now) -> None:
        self._finish(run_id, "failed", failure_code=failure_code, now=now)

    def _finish(self, run_id: int, status: str, *, now, outcome: str | None = None, failure_code: str | None = None) -> None:
        with self.sf() as session:
            try:
                result = session.execute(text("""
                    UPDATE operation_runs SET status=:status, outcome=:outcome,
                    failure_code=:failure_code, finished_at=:now
                    WHERE id=:id AND status='running'
                """), {"id": run_id, "status": status, "outcome": outcome, "failure_code": failure_code, "now": now})
                if result.rowcount != 1:
                    raise InvalidOperationRunTransition("Operation run больше не running")
                session.commit()
            except BaseException:
                session.rollback()
                raise


class SqlAlchemyOperationalStatusRepository:
    def __init__(self, session_factory) -> None:
        self.sf = session_factory

    def snapshot(self, *, day, day_start, day_end, limit: int = 10) -> RawOperationalSnapshot:
        with self.sf() as session:
            try:
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                session.execute(text("SET TRANSACTION READ ONLY"))
                def groups(sql: str, params: dict | None = None) -> tuple[GroupedState, ...]:
                    rows = session.execute(text(sql), params or {}).mappings().all()
                    return tuple(GroupedState(row.code, row.count, tuple(row.ids or ())[:10]) for row in rows)
                candidate_total = session.execute(text("SELECT count(*) FROM candidates")).scalar_one()
                undecided = session.execute(text("""
                    SELECT c.id FROM candidates c LEFT JOIN candidate_decisions d ON d.candidate_id=c.id
                    WHERE d.id IS NULL ORDER BY c.id LIMIT :limit
                """), {"limit": limit}).scalars().all()
                decisions = groups("SELECT status AS code,count(*) AS count,array_agg(candidate_id ORDER BY candidate_id) AS ids FROM candidate_decisions GROUP BY status ORDER BY status")
                rejected = groups("SELECT reason AS code,count(*) AS count,array_agg(candidate_id ORDER BY candidate_id) AS ids FROM candidate_decisions WHERE status='rejected' GROUP BY reason ORDER BY reason")
                attempts = groups("SELECT status AS code,count(*) AS count,array_agg(id ORDER BY id) AS ids FROM content_attempts GROUP BY status ORDER BY status")
                packages = groups("SELECT status AS code,count(*) AS count,array_agg(id ORDER BY id) AS ids FROM content_packages GROUP BY status ORDER BY status")
                delivery = groups("""
                    WITH values AS (
                        SELECT d.status AS code,d.package_id AS id FROM telegram_deliveries d
                        UNION ALL
                        SELECT 'ready' AS code,p.id FROM content_packages p LEFT JOIN telegram_deliveries d ON d.package_id=p.id
                        WHERE p.status='approved' AND (d.id IS NULL OR d.status='retryable')
                    ) SELECT code,count(*) AS count,array_agg(id ORDER BY id) AS ids FROM values GROUP BY code ORDER BY code
                """)
                ready = session.execute(text("""
                    SELECT p.id FROM content_packages p LEFT JOIN telegram_deliveries d ON d.package_id=p.id
                    WHERE p.status='approved' AND (d.id IS NULL OR d.status='retryable') ORDER BY p.id LIMIT :limit
                """), {"limit": limit}).scalars().all()
                cleanup = session.execute(text("SELECT package_id FROM telegram_deliveries WHERE status='published' AND media_deleted_at IS NULL ORDER BY package_id LIMIT :limit"), {"limit": limit}).scalars().all()
                usage = session.execute(text("SELECT analyses_started,packages_created FROM content_daily_usage WHERE day=:day"), {"day": day}).first() or (0, 0)
                published = session.execute(text("SELECT count(*) FROM telegram_deliveries WHERE status='published' AND confirmed_at >= :start AND confirmed_at < :end"), {"start": day_start, "end": day_end}).scalar_one()
                selected_without = session.execute(text("""
                    SELECT d.candidate_id FROM candidate_decisions d LEFT JOIN content_attempts a ON a.candidate_id=d.candidate_id
                    WHERE d.status='selected' AND a.id IS NULL ORDER BY d.candidate_id LIMIT :limit
                """), {"limit": limit}).scalars().all()
                latest_packages = tuple(PackageSummary(row.id, row.status, row.created_at) for row in session.execute(text("SELECT id,status,created_at FROM content_packages ORDER BY created_at DESC,id DESC LIMIT :limit"), {"limit": limit}).mappings())
                latest_attempts = tuple(DeliveryAttemptSummary(row.package_id, row.attempt_no, row.outcome, row.code, row.message_id, row.finished_at) for row in session.execute(text("""
                    SELECT d.package_id,a.attempt_no,a.outcome,a.code,a.finished_at,a.message_id
                    FROM telegram_delivery_attempts a JOIN telegram_deliveries d ON d.id=a.delivery_id
                    ORDER BY a.finished_at DESC,a.id DESC LIMIT :limit
                """), {"limit": limit}).mappings())
                latest_runs = tuple(OperationRunSummary(row.id,row.operation,row.status,row.outcome,row.failure_code,row.finished_at,row.started_at) for row in session.execute(text("SELECT id,operation,status,outcome,failure_code,started_at,finished_at FROM operation_runs ORDER BY COALESCE(finished_at,started_at) DESC,id DESC LIMIT :limit"), {"limit": limit}).mappings())
                session.commit()
                return RawOperationalSnapshot(candidate_total, tuple(undecided), decisions, rejected, attempts, packages, delivery, tuple(ready), tuple(cleanup), usage[0], usage[1], published, tuple(selected_without), latest_packages, latest_attempts, latest_runs)
            except BaseException:
                session.rollback()
                raise
