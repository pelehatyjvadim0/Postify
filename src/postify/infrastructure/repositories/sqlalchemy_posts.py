from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from postify.domain.posts.models import (
    InvalidPostTransition,
    Post,
    PublicationPlanExpired,
    StoredMedia,
    validate_text,
    validate_transition,
)


class SqlAlchemyPostRepository:
    """Посты одного проекта: чтение, редакторские решения, план публикации."""

    def __init__(self, session_factory, project_id: int) -> None:
        self.sf = session_factory
        self.project_id = project_id

    def get_post(self, post_id: int) -> Post:
        with self.sf() as session:
            row = (
                session.execute(
                    text("SELECT * FROM posts WHERE project_id=:project AND id=:id"),
                    {"project": self.project_id, "id": post_id},
                )
                .mappings()
                .one()
            )
            history = session.execute(
                text(
                    "SELECT status,reason,created_at FROM post_status_history"
                    " WHERE project_id=:project AND post_id=:id ORDER BY id"
                ),
                {"project": self.project_id, "id": post_id},
            ).all()
        return Post(
            id=row["id"],
            project_id=row["project_id"],
            post_text=row["post_text"],
            media_path=row["media_path"],
            media_mime=row["media_mime"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            scheduled_at=row["scheduled_at"],
            history=list(history),
        )

    def list_posts(self, *, status: str | None = None, limit: int = 50, offset: int = 0):
        with self.sf() as session:
            ids = session.scalars(
                text(
                    "SELECT id FROM posts WHERE project_id=:project"
                    " AND (:status IS NULL OR status=:status)"
                    " ORDER BY id DESC LIMIT :limit OFFSET :offset"
                ),
                {
                    "project": self.project_id,
                    "status": status,
                    "limit": limit,
                    "offset": offset,
                },
            ).all()
        return tuple(self.get_post(post_id) for post_id in ids)

    def save_plan(self, post_id: int, *, scheduled_at: datetime, now: datetime) -> Post:
        if scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
            raise ValueError("Дата должна содержать часовой пояс")
        scheduled_at = scheduled_at.astimezone(UTC)
        if scheduled_at <= now:
            raise ValueError("Назначьте время в будущем")
        with self.sf() as session:
            with session.begin():
                post = self._locked(session, post_id)
                if post.status not in {"needs_review", "approved"}:
                    raise InvalidPostTransition("План этого поста нельзя изменить")
                delivery = self._delivery_status(session, post_id)
                if delivery in {"sending", "uncertain", "published"}:
                    raise InvalidPostTransition(
                        "Отправка начата или её результат не определён"
                    )
                if post.scheduled_at == scheduled_at:
                    return self.get_post(post_id)
                # Новый план требует повторного одобрения.
                session.execute(
                    text(
                        "UPDATE posts SET scheduled_at=:at,status='needs_review',"
                        "updated_at=:now WHERE project_id=:project AND id=:id"
                    ),
                    {
                        "project": self.project_id,
                        "id": post_id,
                        "at": scheduled_at,
                        "now": now,
                    },
                )
                if delivery == "failed":
                    session.execute(
                        text(
                            "UPDATE deliveries SET status='retryable',updated_at=:now"
                            " WHERE project_id=:project AND post_id=:id"
                        ),
                        {"project": self.project_id, "id": post_id, "now": now},
                    )
                self._history(session, post_id, "needs_review", "plan_changed", now)
        return self.get_post(post_id)

    def approve(self, post_id: int, *, now: datetime) -> Post:
        return self._review(post_id, "approved", now)

    def reject(self, post_id: int, *, now: datetime, reason: str | None = None) -> Post:
        return self._review(post_id, "rejected", now, reason=reason or "review")

    def save_text(self, post_id: int, *, post_text: str, now: datetime) -> Post:
        """Ручная правка редактора: одобренный пост возвращается на ревью."""
        with self.sf() as session:
            with session.begin():
                post = self._locked(session, post_id)
                if post.status not in {"needs_review", "approved"}:
                    raise InvalidPostTransition("Этот пост нельзя редактировать")
                validate_text(post_text, with_media=post.media_path is not None)
                session.execute(
                    text(
                        "UPDATE posts SET post_text=:post_text,status='needs_review',"
                        "updated_at=:now WHERE project_id=:project AND id=:id"
                    ),
                    {
                        "project": self.project_id,
                        "id": post_id,
                        "post_text": post_text,
                        "now": now,
                    },
                )
                self._history(session, post_id, "needs_review", "edited", now)
        return self.get_post(post_id)

    def attach_media(
        self, post_id: int, *, media: StoredMedia | None, now: datetime
    ) -> Post:
        with self.sf() as session:
            with session.begin():
                self._locked(session, post_id)
                session.execute(
                    text(
                        "UPDATE posts SET media_path=:path,media_mime=:mime,"
                        "updated_at=:now WHERE project_id=:project AND id=:id"
                    ),
                    {
                        "project": self.project_id,
                        "id": post_id,
                        "path": media.local_path if media else None,
                        "mime": media.mime if media else None,
                        "now": now,
                    },
                )
        return self.get_post(post_id)

    def active_media_paths(self) -> set[str]:
        with self.sf() as session:
            return set(
                session.scalars(
                    text(
                        "SELECT media_path FROM posts WHERE project_id=:project"
                        " AND media_path IS NOT NULL"
                        " AND status IN ('generating','needs_review','approved')"
                    ),
                    {"project": self.project_id},
                ).all()
            )

    # --- внутреннее -------------------------------------------------------

    def _review(self, post_id: int, status: str, now: datetime, *, reason: str = "review"):
        with self.sf() as session:
            with session.begin():
                post = self._locked(session, post_id)
                if post.status == status:
                    return self.get_post(post_id)
                validate_transition(post.status, status)
                if status == "approved":
                    validate_text(
                        post.post_text, with_media=post.media_path is not None
                    )
                    if post.scheduled_at is None:
                        raise InvalidPostTransition(
                            "Сначала сохраните время публикации"
                        )
                    if post.scheduled_at <= now:
                        raise PublicationPlanExpired(
                            "Время прошло: измените время публикации,"
                            " прежде чем одобрить пост"
                        )
                    self._require_channel(session)
                session.execute(
                    text(
                        "UPDATE posts SET status=:status,updated_at=:now"
                        " WHERE project_id=:project AND id=:id"
                    ),
                    {
                        "project": self.project_id,
                        "id": post_id,
                        "status": status,
                        "now": now,
                    },
                )
                self._history(session, post_id, status, reason, now)
        return self.get_post(post_id)

    def _locked(self, session, post_id: int):
        return (
            session.execute(
                text(
                    "SELECT status,scheduled_at,post_text,media_path FROM posts"
                    " WHERE project_id=:project AND id=:id FOR UPDATE"
                ),
                {"project": self.project_id, "id": post_id},
            )
            .mappings()
            .one()
        )

    def _delivery_status(self, session, post_id: int) -> str | None:
        return session.execute(
            text(
                "SELECT status FROM deliveries"
                " WHERE project_id=:project AND post_id=:id"
            ),
            {"project": self.project_id, "id": post_id},
        ).scalar_one_or_none()

    def _require_channel(self, session) -> None:
        channel = session.execute(
            text(
                "SELECT id FROM channel_connections WHERE project_id=:project"
                " AND enabled AND encrypted_secret IS NOT NULL FOR SHARE"
            ),
            {"project": self.project_id},
        ).scalar_one_or_none()
        if channel is None:
            raise InvalidPostTransition("Канал проекта не настроен")

    def _history(self, session, post_id: int, status: str, reason: str, now) -> None:
        session.execute(
            text(
                "INSERT INTO post_status_history"
                "(project_id,post_id,status,reason,created_at)"
                " VALUES (:project,:id,:status,:reason,:now)"
            ),
            {
                "project": self.project_id,
                "id": post_id,
                "status": status,
                "reason": reason,
                "now": now,
            },
        )
