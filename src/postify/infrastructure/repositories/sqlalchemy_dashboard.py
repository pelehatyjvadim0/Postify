from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text

from postify.application.dashboard.models import (
    DashboardOverview,
    Material,
    Operation,
    PackageDetail,
    PackageHistoryEntry,
    PackageSummary,
    Publication,
    PublicationAttempt,
    QueueSlot,
)


def _bounded(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit должен быть в диапазоне 1–100")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset должен быть неотрицательным")


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _mapping(value: object) -> Mapping[str, object]:
    return _freeze(value if isinstance(value, Mapping) else {})  # type: ignore[return-value]


def _media_status(path: str | None, deleted_at: datetime | None) -> tuple[bool, str]:
    if deleted_at is not None:
        return False, "deleted"
    if path:
        return True, "available"
    return False, "unavailable"


class SqlAlchemyDashboardRepository:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def overview(
        self, project_id: int, day: date, day_start: datetime, day_end: datetime
    ) -> DashboardOverview:
        with self._session_factory() as session:
            try:
                session.connection(
                    execution_options={"isolation_level": "REPEATABLE READ"}
                )
                session.execute(text("SET TRANSACTION READ ONLY"))
                row = (
                    session.execute(
                        text(
                            """SELECT
                        (SELECT count(*) FROM candidates WHERE project_id=:project) AS candidate_total,
                        (SELECT count(*) FROM candidates c WHERE c.project_id=:project
                         AND NOT EXISTS (SELECT 1 FROM candidate_decisions d
                                         WHERE d.project_id=c.project_id AND d.candidate_id=c.id)) AS undecided_materials,
                        (SELECT count(*) FROM candidate_decisions
                         WHERE project_id=:project AND status='selected') AS selected_materials,
                        (SELECT count(*) FROM content_packages WHERE project_id=:project) AS package_total,
                        (SELECT count(*) FROM content_packages
                         WHERE project_id=:project AND status='approved') AS approved_packages,
                        (SELECT count(*) FROM deliveries
                         WHERE project_id=:project AND status='published'
                           AND confirmed_at >= :day_start AND confirmed_at < :day_end) AS published_today,
                        COALESCE((SELECT analyses_started FROM content_daily_usage
                                  WHERE project_id=:project AND day=:day), 0) AS daily_analyses_started,
                        COALESCE((SELECT packages_created FROM content_daily_usage
                                  WHERE project_id=:project AND day=:day), 0) AS daily_packages_created,
                        COALESCE((SELECT manual_analyses_started FROM content_daily_usage
                                  WHERE project_id=:project AND day=:day), 0) AS manual_analyses_started,
                        COALESCE((SELECT manual_packages_created FROM content_daily_usage
                                  WHERE project_id=:project AND day=:day), 0) AS manual_packages_created"""
                        ),
                        {
                            "project": project_id,
                            "day": day,
                            "day_start": day_start,
                            "day_end": day_end,
                        },
                    )
                    .mappings()
                    .one()
                )
                session.commit()
                return DashboardOverview(**dict(row))
            except BaseException:
                session.rollback()
                raise

    def materials(
        self,
        project_id: int,
        status: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Material, ...]:
        _bounded(limit, offset)
        clauses = ["c.project_id=:project"]
        params: dict[str, object] = {
            "project": project_id,
            "limit": limit,
            "offset": offset,
        }
        if status is not None:
            clauses.append("d.status=:status")
            params["status"] = status
        if query is not None:
            clauses.append(
                "(c.source_name ILIKE :query OR c.title ILIKE :query OR c.url ILIKE :query)"
            )
            params["query"] = f"%{query}%"
        with self._session_factory() as session:
            rows = (
                session.execute(
                    text(
                        f"""SELECT c.id AS candidate_id,c.source_name,c.title,c.url,c.discovered_at,
                    d.status AS decision_status,d.reason AS decision_reason,
                    d.explanation AS decision_explanation,d.signals AS decision_signals,d.policy_version,
                    (SELECT a.id FROM content_attempts a WHERE a.project_id=c.project_id
                     AND a.candidate_id=c.id AND a.status IN ('failed','retry_scheduled')
                     ORDER BY a.id DESC LIMIT 1) AS retry_attempt_id
                    FROM candidates c LEFT JOIN candidate_decisions d
                    ON d.project_id=c.project_id AND d.candidate_id=c.id
                    WHERE {" AND ".join(clauses)}
                    ORDER BY c.discovered_at DESC,c.id DESC LIMIT :limit OFFSET :offset"""
                    ),
                    params,
                )
                .mappings()
                .all()
            )
        return tuple(
            Material(
                row.candidate_id,
                row.source_name,
                row.title,
                row.url,
                row.discovered_at,
                row.decision_status,
                row.decision_reason,
                row.decision_explanation,
                None
                if row.decision_signals is None
                else _mapping(row.decision_signals),
                row.policy_version,
                row.retry_attempt_id,
            )
            for row in rows
        )

    def packages(
        self,
        project_id: int,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[PackageSummary, ...]:
        _bounded(limit, offset)
        clauses = ["project_id=:project"]
        params: dict[str, object] = {
            "project": project_id,
            "limit": limit,
            "offset": offset,
        }
        if status is not None:
            clauses.append("status=:status")
            params["status"] = status
        with self._session_factory() as session:
            rows = (
                session.execute(
                    text(
                        """SELECT id,status,source_url,post_text,media_path,media_deleted_at,created_at,updated_at
                    FROM content_packages WHERE """
                        + " AND ".join(clauses)
                        + " ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset"
                    ),
                    params,
                )
                .mappings()
                .all()
            )
        return tuple(
            PackageSummary(
                row.id,
                row.status,
                row.source_url,
                row.post_text,
                *_media_status(row.media_path, row.media_deleted_at),
                row.created_at,
                row.updated_at,
            )
            for row in rows
        )

    def package(self, project_id: int, package_id: int) -> PackageDetail:
        with self._session_factory() as session:
            row = (
                session.execute(
                    text(
                        """SELECT id,attempt_id,status,source_url,post_text,analysis,media_path,media_deleted_at,
                    media_source_type,media_source_url,generation_snapshot,created_at,updated_at
                    FROM content_packages WHERE project_id=:project AND id=:package"""
                    ),
                    {"project": project_id, "package": package_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise LookupError(package_id)
            history = (
                session.execute(
                    text(
                        """SELECT status,reason,created_at FROM content_package_status_history
                    WHERE project_id=:project AND package_id=:package ORDER BY created_at,id"""
                    ),
                    {"project": project_id, "package": package_id},
                )
                .mappings()
                .all()
            )
        return PackageDetail(
            row.id,
            row.status,
            row.source_url,
            row.post_text,
            row.analysis,
            *_media_status(row.media_path, row.media_deleted_at),
            row.media_source_type,
            row.media_source_url,
            tuple(
                PackageHistoryEntry(item.status, item.reason, item.created_at)
                for item in history
            ),
            _mapping(row.generation_snapshot),
            row.created_at,
            row.updated_at,
            row.attempt_id,
        )

    def package_media_path(self, project_id: int, package_id: int) -> tuple[str, str]:
        with self._session_factory() as session:
            row = session.execute(
                text(
                    """SELECT media_path,media_mime FROM content_packages
                    WHERE project_id=:project AND id=:package
                    AND media_path IS NOT NULL AND media_deleted_at IS NULL"""
                ),
                {"project": project_id, "package": package_id},
            ).mappings().first()
        if row is None:
            raise LookupError(package_id)
        return row.media_path, row.media_mime

    def queue(self, project_id: int, day: date) -> tuple[QueueSlot, ...]:
        with self._session_factory() as session:
            routes = (
                session.execute(
                    text(
                        """SELECT r.id AS route_id,c.provider,r.schedule,p.timezone FROM publication_routes r
                    JOIN channel_connections c ON c.id=r.channel_id AND c.project_id=r.project_id
                    JOIN content_projects p ON p.id=r.project_id
                    WHERE r.project_id=:project AND r.enabled AND c.enabled
                    ORDER BY r.id"""
                    ),
                    {"project": project_id},
                )
                .mappings()
                .all()
            )
            if not routes:
                return ()
            route = routes[0]
            day_start = datetime.combine(day, time.min, tzinfo=ZoneInfo(route.timezone))
            day_end = day_start + timedelta(days=1)
            slots = (
                route.schedule.get("slots", ())
                if isinstance(route.schedule, dict)
                else ()
            )
            slots = tuple(slot for slot in slots if isinstance(slot, str))[:3]
            confirmed = (
                session.execute(
                    text(
                        """SELECT id,package_id FROM deliveries WHERE project_id=:project
                    AND (route_id=:route OR (:include_legacy AND route_id IS NULL))
                    AND status='published'
                    AND confirmed_at >= :day_start AND confirmed_at < :day_end
                    ORDER BY confirmed_at,id"""
                    ),
                    {
                        "project": project_id,
                        "route": route.route_id,
                        "include_legacy": len(routes) == 1,
                        "day_start": day_start,
                        "day_end": day_end,
                    },
                )
                .mappings()
                .all()
            )
            forecasts = (
                session.execute(
                    text(
                        """SELECT p.id FROM content_packages p WHERE p.project_id=:project AND p.status='approved'
                    AND NOT EXISTS (SELECT 1 FROM deliveries d
                                    WHERE d.project_id=p.project_id AND d.package_id=p.id)
                    ORDER BY p.created_at,p.id"""
                    ),
                    {"project": project_id},
                )
                .scalars()
                .all()
            )
        assignments = [("confirmed", row.package_id, row.id) for row in confirmed]
        assignments.extend(("forecast", package_id, None) for package_id in forecasts)
        return tuple(
            QueueSlot(
                route.route_id,
                route.provider,
                slot_time,
                assignments[index][0] if index < len(assignments) else "empty",
                assignments[index][1] if index < len(assignments) else None,
                assignments[index][2] if index < len(assignments) else None,
            )
            for index, slot_time in enumerate(slots)
        )

    def publications(
        self, project_id: int, limit: int = 50, offset: int = 0
    ) -> tuple[Publication, ...]:
        _bounded(limit, offset)
        with self._session_factory() as session:
            rows = (
                session.execute(
                    text(
                        """SELECT d.id AS delivery_id,d.package_id,
                    COALESCE(c.provider,d.channel_snapshot->>'provider') AS provider,
                    d.status,d.attempt_no,d.message_id,d.failure_code,d.failure_reason,
                    d.sending_started_at,d.confirmed_at,d.created_at,d.updated_at
                    FROM deliveries d LEFT JOIN channel_connections c
                    ON c.id=d.channel_id AND c.project_id=d.project_id
                    WHERE d.project_id=:project
                    ORDER BY COALESCE(d.confirmed_at,d.updated_at,d.created_at) DESC,d.id DESC
                    LIMIT :limit OFFSET :offset"""
                    ),
                    {"project": project_id, "limit": limit, "offset": offset},
                )
                .mappings()
                .all()
            )
            attempts_by_delivery: dict[int, list[PublicationAttempt]] = {
                row.delivery_id: [] for row in rows
            }
            if attempts_by_delivery:
                attempt_rows = (
                    session.execute(
                        text(
                            """SELECT delivery_id,attempt_no,outcome,code,reason,message_id,
                            started_at,finished_at FROM delivery_attempts
                            WHERE project_id=:project
                            AND delivery_id IN :delivery_ids
                            ORDER BY delivery_id,attempt_no"""
                        ).bindparams(bindparam("delivery_ids", expanding=True)),
                        {
                            "project": project_id,
                            "delivery_ids": tuple(attempts_by_delivery),
                        },
                    )
                    .mappings()
                    .all()
                )
                for item in attempt_rows:
                    attempts_by_delivery[item.delivery_id].append(
                        PublicationAttempt(
                            item.attempt_no,
                            item.outcome,
                            item.code,
                            item.reason,
                            item.message_id,
                            item.started_at,
                            item.finished_at,
                        )
                    )
        return tuple(
            Publication(
                row.delivery_id,
                row.package_id,
                row.provider,
                row.status,
                row.attempt_no,
                tuple(attempts_by_delivery[row.delivery_id]),
                row.message_id,
                row.failure_code,
                row.failure_reason,
                row.sending_started_at,
                row.confirmed_at,
                row.created_at,
                row.updated_at,
            )
            for row in rows
        )

    def operations(
        self, project_id: int, limit: int = 50, offset: int = 0
    ) -> tuple[Operation, ...]:
        _bounded(limit, offset)
        with self._session_factory() as session:
            rows = (
                session.execute(
                    text(
                        """SELECT id,operation,status,outcome,failure_code,started_at,finished_at,mode,actor,
                        codex_model,codex_reasoning_effort,materials_taken,packages_created
                    FROM operation_runs WHERE project_id=:project
                    ORDER BY COALESCE(finished_at,started_at) DESC,id DESC LIMIT :limit OFFSET :offset"""
                    ),
                    {"project": project_id, "limit": limit, "offset": offset},
                )
                .mappings()
                .all()
            )
        return tuple(
            Operation(
                row.id,
                row.operation,
                row.status,
                row.outcome,
                row.failure_code,
                row.started_at,
                row.finished_at,
                None if row.finished_at is None else row.finished_at - row.started_at,
                row.mode,
                row.actor,
                row.codex_model,
                row.codex_reasoning_effort,
                row.materials_taken,
                row.packages_created,
            )
            for row in rows
        )

    def operation(self, project_id: int, run_id: int) -> Operation:
        with self._session_factory() as session:
            row = session.execute(
                text(
                    """SELECT id,operation,status,outcome,failure_code,started_at,finished_at,mode,actor,
                    codex_model,codex_reasoning_effort,materials_taken,packages_created
                    FROM operation_runs WHERE project_id=:project AND id=:run"""
                ),
                {"project": project_id, "run": run_id},
            ).mappings().first()
        if row is None:
            raise LookupError(run_id)
        return Operation(
            row.id, row.operation, row.status, row.outcome, row.failure_code,
            row.started_at, row.finished_at,
            None if row.finished_at is None else row.finished_at - row.started_at,
            row.mode, row.actor, row.codex_model, row.codex_reasoning_effort,
            row.materials_taken, row.packages_created,
        )
