from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text

from postify.application.dashboard.models import (
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
            clauses.append("latest.status=:status")
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
                        f"""SELECT c.id AS candidate_id,c.source_name,c.title,c.url,c.discovered_at,c.source_text,
                    CASE WHEN latest.status IN ('failed','retry_scheduled') THEN latest.id END AS retry_attempt_id,
                    latest.status AS generation_status,latest.failure_code AS generation_failure_code
                    FROM candidates c LEFT JOIN LATERAL (
                        SELECT a.id,a.status,a.failure_code FROM content_attempts a
                        WHERE a.project_id=c.project_id AND a.candidate_id=c.id
                        ORDER BY a.attempt_no DESC,a.id DESC LIMIT 1
                    ) latest ON true
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
                row.retry_attempt_id,
                generation_status=row.generation_status,
                generation_failure_code=row.generation_failure_code,
                original_text=row.source_text,
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
                        """SELECT id,status,source_url,post_text,media_path,media_deleted_at,created_at,updated_at,scheduled_at,route_id,previous_package_id,
                    (SELECT a.candidate_id FROM content_attempts a WHERE a.id=content_packages.attempt_id AND a.project_id=content_packages.project_id) AS candidate_id
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
                scheduled_at=row.scheduled_at, route_id=row.route_id,
                candidate_id=row.candidate_id, previous_package_id=row.previous_package_id,
            )
            for row in rows
        )

    def package(self, project_id: int, package_id: int) -> PackageDetail:
        with self._session_factory() as session:
            row = (
                session.execute(
                    text(
                        """SELECT id,attempt_id,status,source_url,post_text,analysis,media_path,media_deleted_at,
                    media_source_type,media_source_url,generation_snapshot,created_at,updated_at,context,scheduled_at,route_id,
                    (SELECT d.status FROM deliveries d WHERE d.project_id=content_packages.project_id AND d.package_id=content_packages.id) AS delivery_status,
                    (SELECT p.id FROM content_packages p WHERE p.project_id=content_packages.project_id AND p.previous_package_id=content_packages.id AND p.status='awaiting_review' ORDER BY p.id DESC LIMIT 1) AS replacement_package_id
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
            original_text=row.context, scheduled_at=row.scheduled_at, route_id=row.route_id,
            delivery_status=row.delivery_status,
            replacement_package_id=row.replacement_package_id,
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
            timezone = session.execute(text("SELECT timezone FROM content_projects WHERE id=:project"), {"project": project_id}).scalar_one()
            day_start = datetime.combine(day, time.min, tzinfo=ZoneInfo(timezone))
            rows = session.execute(text("""
                SELECT p.id,p.scheduled_at,p.route_id,p.status,p.post_text,
                       c.provider,c.name AS channel_name,d.id AS delivery_id,
                       d.status AS delivery_status,d.failure_code,d.failure_reason
                FROM content_packages p
                JOIN content_projects project ON project.id=p.project_id
                JOIN publication_routes r ON r.id=p.route_id AND r.project_id=p.project_id
                JOIN channel_connections c ON c.id=r.channel_id AND c.project_id=r.project_id
                LEFT JOIN deliveries d ON d.package_id=p.id AND d.project_id=p.project_id
                WHERE p.project_id=:project AND (p.status IN ('awaiting_review','approved')
                    OR (p.status='published' AND p.scheduled_at>=:start AND p.scheduled_at<:end))
                ORDER BY p.scheduled_at,p.id
            """), {"project": project_id, "start": day_start, "end": day_start + timedelta(days=1)}).mappings().all()
        return tuple(QueueSlot(row.route_id,row.provider,row.scheduled_at.astimezone(ZoneInfo(timezone)).strftime("%H:%M"),
            "confirmed" if row.delivery_status == "published" else "planned", row.id,row.delivery_id,
            scheduled_at=row.scheduled_at,status=row.status,delivery_status=row.delivery_status,
            channel_name=row.channel_name,post_text=row.post_text,failure_code=row.failure_code,
            failure_reason=row.failure_reason) for row in rows)

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
