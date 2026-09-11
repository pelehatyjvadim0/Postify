from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType

from sqlalchemy import bindparam, text

from postify.application.dashboard.models import (
    Operation,
    PostDetail,
    PostHistoryEntry,
    PostSummary,
    Publication,
    PublicationAttempt,
)


# Список постов показывает превью, а не весь текст: полный отдаёт карточка.
EXCERPT_LIMIT = 200


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


class SqlAlchemyDashboardRepository:
    """Чтение для UI: посты, журнал операций и публикации.

    Слой тонкий: только выборки. Каждый запрос фильтрует по ``project_id`` —
    это изоляция данных, чужой проект обязан выглядеть пустым.
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def posts(
        self,
        project_id: int,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[PostSummary, ...]:
        _bounded(limit, offset)
        clauses = ["p.project_id=:project"]
        params: dict[str, object] = {
            "project": project_id,
            "limit": limit,
            "offset": offset,
            "excerpt": EXCERPT_LIMIT,
        }
        if status is not None:
            clauses.append("p.status=:status")
            params["status"] = status
        with self._session_factory() as session:
            rows = (
                session.execute(
                    text(
                        f"""SELECT p.id,p.status,left(p.post_text,:excerpt) AS excerpt,
                        char_length(p.post_text) AS char_count,
                        (p.media_path IS NOT NULL AND p.media_deleted_at IS NULL) AS media_available,
                        p.created_at,p.updated_at,p.scheduled_at,d.status AS delivery_status,
                        s.id AS slot_id,s.topic,s.publish_at,s.rubric_id,r.name AS rubric_name
                        FROM posts p
                        LEFT JOIN content_plan_slots s
                            ON s.project_id=p.project_id AND s.post_id=p.id
                        LEFT JOIN project_rubrics r
                            ON r.project_id=s.project_id AND r.id=s.rubric_id
                        LEFT JOIN deliveries d
                            ON d.project_id=p.project_id AND d.post_id=p.id
                        WHERE {" AND ".join(clauses)}
                        ORDER BY p.created_at DESC,p.id DESC LIMIT :limit OFFSET :offset"""
                    ),
                    params,
                )
                .mappings()
                .all()
            )
        return tuple(
            PostSummary(
                row.id,
                row.status,
                row.excerpt,
                row.char_count,
                row.media_available,
                row.created_at,
                row.updated_at,
                scheduled_at=row.scheduled_at,
                delivery_status=row.delivery_status,
                slot_id=row.slot_id,
                topic=row.topic or "",
                publish_at=row.publish_at,
                rubric_id=row.rubric_id,
                rubric_name=row.rubric_name,
            )
            for row in rows
        )

    def post(self, project_id: int, post_id: int) -> PostDetail:
        with self._session_factory() as session:
            row = (
                session.execute(
                    text(
                        """SELECT p.id,p.status,p.post_text,char_length(p.post_text) AS char_count,
                        (p.media_path IS NOT NULL AND p.media_deleted_at IS NULL) AS media_available,
                        p.media_mime,p.generation,p.created_at,p.updated_at,p.scheduled_at,
                        d.status AS delivery_status,d.message_id AS delivery_message_id,
                        d.failure_code,d.failure_reason,d.confirmed_at,
                        s.id AS slot_id,a.id AS media_asset_id,a.caption AS media_caption,
                        a.last_used_at AS media_last_used_at,
                        COALESCE(d.channel_snapshot->'configuration'->>'chat_id',
                                 c.configuration->>'chat_id') AS channel_chat_id
                        FROM posts p
                        LEFT JOIN content_plan_slots s
                            ON s.project_id=p.project_id AND s.post_id=p.id
                        LEFT JOIN media_assets a
                            ON a.project_id=p.project_id
                           AND a.id=CASE WHEN (p.generation->>'media_asset_id') ~ '^[0-9]+$'
                                THEN (p.generation->>'media_asset_id')::bigint END
                        LEFT JOIN deliveries d
                            ON d.project_id=p.project_id AND d.post_id=p.id
                        LEFT JOIN channel_connections c
                            ON c.project_id=p.project_id AND c.id=d.channel_id
                        WHERE p.project_id=:project AND p.id=:post"""
                    ),
                    {"project": project_id, "post": post_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise LookupError(post_id)
            history = (
                session.execute(
                    text(
                        """SELECT status,reason,created_at FROM post_status_history
                        WHERE project_id=:project AND post_id=:post
                        ORDER BY created_at,id"""
                    ),
                    {"project": project_id, "post": post_id},
                )
                .mappings()
                .all()
            )
        return PostDetail(
            row.id,
            row.status,
            row.post_text,
            row.char_count,
            row.media_available,
            row.media_mime,
            _mapping(row.generation),
            tuple(
                PostHistoryEntry(item.status, item.reason, item.created_at)
                for item in history
            ),
            row.created_at,
            row.updated_at,
            scheduled_at=row.scheduled_at,
            delivery_status=row.delivery_status,
            delivery_message_id=row.delivery_message_id,
            failure_code=row.failure_code,
            failure_reason=row.failure_reason,
            published_at=row.confirmed_at,
            slot_id=row.slot_id,
            media_asset_id=row.media_asset_id,
            media_caption=row.media_caption,
            media_last_used_at=row.media_last_used_at,
            channel_chat_id=row.channel_chat_id,
        )

    def post_media_path(self, project_id: int, post_id: int) -> tuple[str, str]:
        with self._session_factory() as session:
            row = (
                session.execute(
                    text(
                        """SELECT media_path,media_mime FROM posts
                        WHERE project_id=:project AND id=:post
                        AND media_path IS NOT NULL AND media_deleted_at IS NULL"""
                    ),
                    {"project": project_id, "post": post_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise LookupError(post_id)
        return row.media_path, row.media_mime

    def operations(
        self, project_id: int, *, limit: int = 50, offset: int = 0
    ) -> tuple[Operation, ...]:
        _bounded(limit, offset)
        with self._session_factory() as session:
            rows = (
                session.execute(
                    text(
                        """SELECT id,operation,status,outcome,failure_code,mode,actor,result,
                        started_at,finished_at FROM operation_runs
                        WHERE project_id=:project
                        ORDER BY COALESCE(finished_at,started_at) DESC,id DESC
                        LIMIT :limit OFFSET :offset"""
                    ),
                    {"project": project_id, "limit": limit, "offset": offset},
                )
                .mappings()
                .all()
            )
        return tuple(_operation(row) for row in rows)

    def operation(self, project_id: int, operation_run_id: int) -> Operation:
        with self._session_factory() as session:
            row = (
                session.execute(
                    text(
                        """SELECT id,operation,status,outcome,failure_code,mode,actor,result,
                        started_at,finished_at FROM operation_runs
                        WHERE project_id=:project AND id=:run"""
                    ),
                    {"project": project_id, "run": operation_run_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise LookupError(operation_run_id)
        return _operation(row)

    def publications(
        self, project_id: int, *, limit: int = 50, offset: int = 0
    ) -> tuple[Publication, ...]:
        _bounded(limit, offset)
        with self._session_factory() as session:
            rows = (
                session.execute(
                    text(
                        """SELECT d.id AS delivery_id,d.post_id,
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
                row.post_id,
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


def _operation(row) -> Operation:
    finished_at: datetime | None = row.finished_at
    return Operation(
        row.id,
        row.operation,
        row.status,
        row.outcome,
        row.failure_code,
        row.mode,
        row.actor,
        _mapping(row.result),
        row.started_at,
        finished_at,
        None if finished_at is None else finished_at - row.started_at,
    )
