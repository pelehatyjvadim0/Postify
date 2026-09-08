from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import text


_LOCK = """
    SELECT pg_try_advisory_lock(
        hashtextextended('postify-content:' || CAST(:project AS text), 0)
    )
"""
_UNLOCK = """
    SELECT pg_advisory_unlock(
        hashtextextended('postify-content:' || CAST(:project AS text), 0)
    )
"""


def _engine(session_factory):
    with session_factory() as session:
        return session.get_bind()


@contextmanager
def generation_lock(session_factory, project_id: int):
    """Keep one project content generation active across independent sessions."""
    with _engine(session_factory).connect() as connection:
        acquired = connection.execute(text(_LOCK), {"project": project_id}).scalar_one()
        connection.commit()
        if not acquired:
            raise RuntimeError("content_busy")
        try:
            yield
        finally:
            try:
                connection.execute(text(_UNLOCK), {"project": project_id})
                connection.commit()
            except BaseException:
                connection.invalidate()
                raise


def recover_interrupted_content(session_factory, project_id: int, now) -> int:
    """Fail only content left by a process whose session advisory lock vanished."""
    with _engine(session_factory).connect() as connection:
        acquired = connection.execute(text(_LOCK), {"project": project_id}).scalar_one()
        if not acquired:
            connection.rollback()
            return 0
        try:
            package_ids = connection.scalars(
                text(
                    "UPDATE content_packages SET status='failed',updated_at=:now "
                    "WHERE project_id=:project AND status='processing' RETURNING id"
                ),
                {"project": project_id, "now": now},
            ).all()
            if package_ids:
                connection.execute(
                    text(
                        "INSERT INTO content_package_status_history"
                        "(project_id,package_id,status,reason,created_at) "
                        "VALUES (:project,:package,'failed','processing_interrupted',:now)"
                    ),
                    [
                        {"project": project_id, "package": package_id, "now": now}
                        for package_id in package_ids
                    ],
                )
            attempt_ids = connection.scalars(
                text(
                    "UPDATE content_attempts SET status='failed',"
                    "failure_code='processing_interrupted',retry_at=NULL,finished_at=:now "
                    "WHERE project_id=:project AND status='processing' RETURNING id"
                ),
                {"project": project_id, "now": now},
            ).all()
            recovered_runs = connection.execute(
                text(
                    "UPDATE operation_runs SET status='failed',outcome=NULL,"
                    "failure_code=operation || '_failed',finished_at=:now "
                    "WHERE project_id=:project AND status='running' "
                    "AND operation IN ('run_once','retry_analysis','return_to_analysis',"
                    "'regenerate_post','manual_search') RETURNING id,operation"
                ),
                {"project": project_id, "now": now},
            ).mappings().all()
            run_once_ids = [row["id"] for row in recovered_runs if row["operation"] == "run_once"]
            if run_once_ids:
                connection.execute(
                    text(
                        "UPDATE scheduled_jobs SET status='failed',lease_expires_at=NULL,"
                        "updated_at=:now WHERE project_id=:project AND kind='run_once' "
                        "AND status IN ('queued','leased') "
                        "AND operation_run_id = ANY(:run_ids)"
                    ),
                    {"project": project_id, "now": now, "run_ids": run_once_ids},
                )
            connection.commit()
            return len(package_ids) + len(attempt_ids)
        except BaseException:
            connection.rollback()
            raise
        finally:
            try:
                connection.execute(text(_UNLOCK), {"project": project_id})
                connection.commit()
            except BaseException:
                connection.invalidate()
                raise
