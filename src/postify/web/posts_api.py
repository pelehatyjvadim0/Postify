"""Веб-фасад постов — раздел 8 контракта API.

Отдельный класс, а не методы в ``WebApplication``: пост тянет за собой
конвейер генерации (шлюз вызовов модели, пул изображений, слои проверок), и
держать его рядом с доставкой и проектами означало бы смешивать несвязанные
графы зависимостей. Так же выделен пул изображений (``web/media_api.py``).

Границы ответственности: сюда приходит уже проверенный на владение проект
(``owned_project`` стоит на роутере), здесь собирается представление
контракта, а сценарии живут в ``application``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from postify.infrastructure.repositories.sqlalchemy_dashboard import (
    SqlAlchemyDashboardRepository,
)
from postify.infrastructure.repositories.sqlalchemy_posts import SqlAlchemyPostRepository
from postify.infrastructure.repositories.sqlalchemy_projects import (
    SqlAlchemyProjectRepository,
)
from postify.web.views import at, plain


class PostsApi:
    """Действия постов для HTTP-слоя."""

    def __init__(
        self,
        session_factory,
        settings,
        *,
        operations,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = session_factory
        self._settings = settings
        self._operations = operations
        self._dashboard = SqlAlchemyDashboardRepository(session_factory)
        self._projects = SqlAlchemyProjectRepository(session_factory)
        self._now = clock

    # --- чтение -----------------------------------------------------------

    def posts(
        self,
        project_id: int,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        zone = self._zone(project_id)
        items = self._dashboard.posts(
            project_id, status=status, limit=limit, offset=offset
        )
        return [_post_summary(item, zone) for item in items]

    def post(self, project_id: int, post_id: int) -> dict[str, Any]:
        detail = self._dashboard.post(project_id, post_id)
        return _post(detail, self._zone(project_id), project_id=project_id)

    def post_media(self, project_id: int, post_id: int) -> tuple[bytes, str]:
        media_path, media_mime = self._dashboard.post_media_path(project_id, post_id)
        try:
            return Path(media_path).read_bytes(), media_mime
        except OSError:
            # Файл удалён уборкой после публикации: для клиента это 404.
            raise LookupError(post_id) from None

    # --- решения редактора ------------------------------------------------

    def update_post(
        self,
        project_id: int,
        post_id: int,
        *,
        post_text: str | None = None,
        scheduled_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Правка редактора: время публикации и текст поста.

        ``scheduled_at`` здесь временно — до появления слотов контент-плана,
        которые станут единственным местом планирования.
        """
        posts = self._posts_for(project_id)
        if scheduled_at is not None:
            posts.save_plan(post_id, scheduled_at=scheduled_at, now=self._now())
        if post_text is not None:
            posts.save_text(post_id, post_text=post_text, now=self._now())
        return self.post(project_id, post_id)

    def approve_post(self, project_id: int, post_id: int) -> dict[str, Any]:
        self._posts_for(project_id).approve(post_id, now=self._now())
        return self.post(project_id, post_id)

    def reject_post(self, project_id: int, post_id: int) -> dict[str, Any]:
        self._posts_for(project_id).reject(post_id, now=self._now())
        return self.post(project_id, post_id)

    # --- внутреннее -------------------------------------------------------

    def _posts_for(self, project_id: int) -> SqlAlchemyPostRepository:
        return SqlAlchemyPostRepository(self._sessions, project_id)

    def _zone(self, project_id: int) -> ZoneInfo:
        return ZoneInfo(self._projects.get(project_id).timezone)


def _post_summary(item, zone: ZoneInfo) -> dict[str, Any]:
    return {
        "id": item.id,
        "status": item.status,
        "excerpt": item.excerpt,
        "char_count": item.char_count,
        "media_available": item.media_available,
        "scheduled_at": at(item.scheduled_at, zone),
        "delivery_status": item.delivery_status,
        "created_at": at(item.created_at, zone),
        "updated_at": at(item.updated_at, zone),
    }


def _post(item, zone: ZoneInfo, *, project_id: int) -> dict[str, Any]:
    delivery = (
        None
        if item.delivery_status is None
        else {
            "status": item.delivery_status,
            "message_id": item.delivery_message_id,
            "failure_code": item.failure_code,
            "failure_reason": item.failure_reason,
            "published_at": at(item.published_at, zone),
        }
    )
    return {
        "id": item.id,
        # Слот контент-плана появится вместе с треком генерации.
        "slot_id": None,
        "status": item.status,
        "post_text": item.post_text,
        "char_count": item.char_count,
        "scheduled_at": at(item.scheduled_at, zone),
        "media": (
            {
                "url": f"/api/projects/{project_id}/posts/{item.id}/media",
                "mime": item.media_mime,
            }
            if item.media_available
            else None
        ),
        "generation": plain(item.generation),
        # Отчёт слоёв проверок принесёт свой трек.
        "validation": None,
        "delivery": delivery,
        "published": at(item.published_at, zone),
        "history": [
            {
                "status": entry.status,
                "reason": entry.reason,
                "created_at": at(entry.created_at, zone),
            }
            for entry in item.history
        ],
        "created_at": at(item.created_at, zone),
        "updated_at": at(item.updated_at, zone),
    }
