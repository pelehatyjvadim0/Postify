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

from postify.application.ports.validation import DraftMedia, PostDraft
from postify.application.validation.service import ValidationService
from postify.infrastructure.repositories.sqlalchemy_dashboard import (
    SqlAlchemyDashboardRepository,
)
from postify.infrastructure.repositories.sqlalchemy_generation import (
    SqlAlchemyGenerationRepository,
)
from postify.infrastructure.repositories.sqlalchemy_media import SqlAlchemyMediaRepository
from postify.infrastructure.repositories.sqlalchemy_posts import SqlAlchemyPostRepository
from postify.infrastructure.repositories.sqlalchemy_projects import (
    SqlAlchemyProjectRepository,
)
from postify.infrastructure.repositories.sqlalchemy_validation import (
    SqlAlchemyValidationJournal,
)
from postify.web.views import at, checks_summary, plain


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
        self._validation = SqlAlchemyValidationJournal(session_factory)

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
        reports = self._validation.reports([item.id for item in items])
        return [_post_summary(item, zone, reports.get(item.id)) for item in items]

    def post(self, project_id: int, post_id: int) -> dict[str, Any]:
        detail = self._dashboard.post(project_id, post_id)
        return _post(detail, self._zone(project_id), project_id=project_id, validation=self._validation.report(post_id))

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
        media_asset_id: int | None = None,
    ) -> dict[str, Any]:
        """Правка текста или изображения возвращает пост на ревью."""
        posts = self._posts_for(project_id)
        if post_text is not None:
            posts.save_text(post_id, post_text=post_text, now=self._now())
        if media_asset_id is not None:
            posts.select_media_asset(post_id, asset_id=media_asset_id, now=self._now())
        if post_text is not None or media_asset_id is not None:
            self._validate_edit(project_id, post_id)
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

    def _validate_edit(self, project_id: int, post_id: int) -> None:
        brief = SqlAlchemyGenerationRepository(self._sessions, project_id).brief_for_post(post_id)
        detail = self._dashboard.post(project_id, post_id)
        media = None
        if detail.media_asset_id is not None:
            asset = SqlAlchemyMediaRepository(self._sessions, project_id).get(detail.media_asset_id, now=self._now())
            media = DraftMedia(asset.id, asset.file_path, asset.mime, asset.caption)
        report = ValidationService().validate_edit(
            PostDraft(project_id, detail.post_text, brief.slot, media, brief.user_id)
        )
        self._validation.save(post_id, iteration=0, report=report, now=self._now())


def _post_summary(item, zone: ZoneInfo, validation=None) -> dict[str, Any]:
    return {
        "id": item.id,
        "slot_id": item.slot_id,
        "status": "planned" if item.status == "rejected" else item.status,
        "title": item.topic or item.excerpt,
        "excerpt": item.excerpt,
        "publish_at": at(item.publish_at, zone),
        "rubric": None if item.rubric_id is None else {"id": item.rubric_id, "name": item.rubric_name},
        "checks_summary": checks_summary(validation),
    }


def _post(item, zone: ZoneInfo, *, project_id: int, validation: dict[str, Any] | None = None) -> dict[str, Any]:
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
        "slot_id": item.slot_id,
        "status": "planned" if item.status == "rejected" else item.status,
        "post_text": item.post_text,
        "char_count": item.char_count,
        "media": (
            {
                "asset_id": item.media_asset_id,
                "caption": item.media_caption or "",
                "url": f"/api/projects/{project_id}/media/{item.media_asset_id}/file",
                "rationale": str(item.generation.get("media_rationale", "")),
                "last_used_at": at(item.media_last_used_at, zone),
            }
            if item.media_available and item.media_asset_id is not None
            else None
        ),
        "generation": plain(item.generation) or None,
        "validation": validation or {"passed": False, "iterations": 0, "layers": []},
        "delivery": delivery,
        "published": _published(item, zone),
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


def _published(item, zone: ZoneInfo):
    if item.published_at is None:
        return None
    chat_id = item.channel_chat_id or ""
    if chat_id.startswith("@"):
        target = chat_id[1:]
    elif chat_id.startswith("-100"):
        target = f"c/{chat_id[4:]}"
    else:
        target = chat_id
    return {
        "published_at": at(item.published_at, zone),
        "message_url": f"https://t.me/{target}/{item.delivery_message_id}" if target and item.delivery_message_id else "",
    }
