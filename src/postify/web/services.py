"""Фасад веб-приложения: composition root и все действия HTTP-слоя.

Роутеры знают только методы этого класса. Здесь же собираются репозитории,
пул ограниченных операций и тик планировщика, поэтому веб-слой нигде не
встречается с SQLAlchemy напрямую.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import sessionmaker

from postify.application.delivery.manual_operations import DeliveryNotRetryable
from postify.application.projects.check_channel import CheckChannel
from postify.application.projects.manage_channel import (
    RemoveProjectChannel,
    SetProjectChannel,
    channel_view,
)
from postify.application.plan.service import PlanService
from postify.application.projects.manage_project import ManageProject
from postify.application.projects.manage_rubrics import ManageRubrics
from postify.application.scheduling.project_scheduler import (
    ProjectScheduler,
    ScheduledCommand,
)
from postify.bootstrap import open_project_publish_once, project_manual_delivery_retry
from postify.config import Settings
from postify.domain.observability.models import OperationKind
from postify.domain.projects.models import ContentProject
from postify.infrastructure.database.engine import create_engine_from_settings
from postify.infrastructure.repositories.sqlalchemy_dashboard import (
    SqlAlchemyDashboardRepository,
)
from postify.infrastructure.repositories.sqlalchemy_observability import (
    SqlAlchemyOperationRunRepository,
)
from postify.infrastructure.repositories.sqlalchemy_plan import SqlAlchemyPlanRepository
from postify.infrastructure.repositories.sqlalchemy_posts import SqlAlchemyPostRepository
from postify.infrastructure.repositories.sqlalchemy_projects import (
    SqlAlchemyProjectRepository,
)
from postify.infrastructure.repositories.sqlalchemy_schedule import (
    SqlAlchemyScheduleRepository,
)
from postify.infrastructure.security.secrets import SecretCipher
from postify.web.errors import ConflictError, message_for
from postify.web.media_api import MediaApi


# Политика повторов изображений ещё без хранения: её принесёт трек пула.
DEFAULT_MEDIA_REUSE_DAYS = 30

# Операции, которые веб-слой умеет выполнять сам. Генерация и перегенерация
# появятся вместе со шлюзом вызовов модели.
SUPPORTED_OPERATIONS = frozenset(
    {OperationKind.PUBLISH_ONCE, OperationKind.RETRY_DELIVERY}
)


class BoundedOperations:
    """Ограничивает параллельные операции UI и отсекает дубли по виду."""

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="postify-web"
        )
        self._active: set[tuple[int, str]] = set()
        self._lock = Lock()
        self._closed = False

    def submit(self, project_id: int, kind: str, operation) -> None:
        key = (project_id, kind)
        with self._lock:
            if self._closed:
                raise RuntimeError("operation_closed")
            if key in self._active:
                raise RuntimeError("operation_busy")
            self._active.add(key)

        def run() -> None:
            try:
                operation()
            finally:
                with self._lock:
                    self._active.discard(key)

        self._executor.submit(run)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=False)


class WebApplication:
    """Composition facade; роутеры только отображают транспорт в эти действия."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = create_engine_from_settings(settings)
        self._sessions = sessionmaker(self._engine)
        self._projects = SqlAlchemyProjectRepository(self._sessions)
        self._dashboard = SqlAlchemyDashboardRepository(self._sessions)
        self._schedule_repository = SqlAlchemyScheduleRepository(self._sessions)
        self._scheduler = ProjectScheduler(
            self._schedule_repository, self._submit_scheduled
        )
        self._operations = BoundedOperations()
        self._media = MediaApi(
            self._sessions, settings, operations=self._operations, clock=self._now
        )
        self._cipher = (
            SecretCipher(settings.postify_secret_key.get_secret_value())
            if settings.postify_secret_key is not None
            else None
        )
        self._manage_projects = ManageProject(self._projects, clock=self._now)
        self._manage_rubrics = ManageRubrics(self._projects, clock=self._now)
        self._plan = PlanService(
            lambda project_id: SqlAlchemyPlanRepository(self._sessions, project_id),
            clock=self._now,
            submit_generation=self._start_generation,
        )

    # --- жизненный цикл ---------------------------------------------------

    def scheduler_tick(self) -> tuple[ScheduledCommand, ...]:
        return self._scheduler.tick(self._now())

    def close(self) -> None:
        self._operations.close()
        self._engine.dispose()

    # --- проекты ----------------------------------------------------------

    def list_projects(self, *, owner_id: int) -> list[dict[str, Any]]:
        """Проекты одного пользователя.

        Фильтр по владельцу обязан быть в самом запросе: коллекция проектов —
        единственный маршрут без ``project_id``, а значит и без общей проверки
        владения.
        """
        return [
            {
                "id": project.id,
                "name": project.name,
                "channel_title": self._channel_view(project.id)["chat_id"] or None,
                "publication_mode": project.publication_mode,
                "counts": self._projects.post_counts(project.id),
            }
            for project in self._manage_projects.list(owner_id=owner_id)
        ]

    def create_project(
        self, payload: dict[str, object], *, owner_id: int
    ) -> dict[str, Any]:
        """Заводит проект на текущего пользователя: владелец обязателен."""
        return self._project_view(
            self._manage_projects.create(payload, owner_id=owner_id)
        )

    def project(self, project_id: int) -> dict[str, Any]:
        return self._project_view(self._manage_projects.get(project_id))

    def update_project(
        self, project_id: int, payload: dict[str, object]
    ) -> dict[str, Any]:
        return self._project_view(self._manage_projects.update(project_id, payload))

    def delete_project(self, project_id: int) -> None:
        self._manage_projects.delete(project_id)

    # --- пул изображений --------------------------------------------------

    def media_upload_limit(self) -> int:
        return self._media.media_upload_limit()

    def media_assets(
        self,
        project_id: int,
        *,
        available: bool | None = None,
        query: str | None = None,
        limit: int = 60,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self._media.media_assets(
            project_id, available=available, query=query, limit=limit, cursor=cursor
        )

    def upload_media(
        self, project_id: int, payloads: Sequence[bytes]
    ) -> dict[str, Any]:
        return self._media.upload_media(project_id, payloads)

    def media_file(
        self, project_id: int, asset_id: int, *, size: str = "full"
    ) -> tuple[bytes, str]:
        return self._media.media_file(project_id, asset_id, size=size)

    def update_media(
        self,
        project_id: int,
        asset_id: int,
        *,
        caption: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        return self._media.update_media(
            project_id, asset_id, caption=caption, enabled=enabled
        )

    def delete_media(self, project_id: int, asset_id: int) -> None:
        self._media.delete_media(project_id, asset_id)

    def recaption_media(self, project_id: int, asset_id: int) -> dict[str, Any]:
        return self._media.recaption_media(project_id, asset_id)

    # --- контент-план -----------------------------------------------------

    def plan(
        self, project_id: int, *, date_from: date, date_to: date
    ) -> list[dict[str, Any]]:
        return self._plan.list(project_id, date_from=date_from, date_to=date_to)

    def create_slot(self, project_id: int, payload: dict[str, object]) -> dict[str, Any]:
        return self._plan.create(project_id, payload)

    def update_slot(
        self, project_id: int, slot_id: int, payload: dict[str, object]
    ) -> dict[str, Any]:
        return self._plan.update(project_id, slot_id, payload)

    def delete_slot(self, project_id: int, slot_id: int) -> None:
        self._plan.delete(project_id, slot_id)

    def skip_slot(self, project_id: int, slot_id: int) -> dict[str, Any]:
        return self._plan.skip(project_id, slot_id)

    def generate_slot(self, project_id: int, slot_id: int) -> dict[str, Any]:
        return self._plan.generate(project_id, slot_id)

    # --- канал ------------------------------------------------------------

    def set_channel(
        self, project_id: int, *, bot_token: str, chat_id: str
    ) -> dict[str, Any]:
        SetProjectChannel(self._projects, self._cipher, clock=self._now).execute(
            project_id, bot_token=bot_token, chat_id=chat_id
        )
        return self._channel_view(project_id)

    def check_channel(self, project_id: int) -> dict[str, Any]:
        from postify.adapters.channels.telegram_check import TelegramChannelChecker

        with httpx.Client() as client:
            CheckChannel(
                self._projects,
                self._cipher,
                TelegramChannelChecker(client),
                clock=self._now,
            ).execute(project_id)
        return self._channel_view(project_id)

    def remove_channel(self, project_id: int) -> None:
        RemoveProjectChannel(self._projects).execute(project_id)

    # --- рубрики ----------------------------------------------------------

    def rubrics(self, project_id: int) -> list[dict[str, Any]]:
        return [_rubric(item) for item in self._manage_rubrics.list(project_id)]

    def create_rubric(
        self, project_id: int, payload: dict[str, object]
    ) -> dict[str, Any]:
        return _rubric(self._manage_rubrics.create(project_id, payload))

    def update_rubric(
        self, project_id: int, rubric_id: int, payload: dict[str, object]
    ) -> dict[str, Any]:
        return _rubric(self._manage_rubrics.update(project_id, rubric_id, payload))

    def delete_rubric(self, project_id: int, rubric_id: int) -> None:
        self._manage_rubrics.delete(project_id, rubric_id)

    # --- посты ------------------------------------------------------------

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

    def post_media(self, project_id: int, post_id: int) -> tuple[bytes, str]:
        media_path, media_mime = self._dashboard.post_media_path(project_id, post_id)
        try:
            return Path(media_path).read_bytes(), media_mime
        except OSError:
            # Файл удалён уборкой после публикации: для клиента это 404.
            raise LookupError(post_id) from None

    # --- журнал и публикации ---------------------------------------------

    def operations(
        self, project_id: int, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        zone = self._zone(project_id)
        return [
            _operation(item, zone)
            for item in self._dashboard.operations(
                project_id, limit=limit, offset=offset
            )
        ]

    def operation(self, project_id: int, operation_id: int) -> dict[str, Any]:
        return _operation(
            self._dashboard.operation(project_id, operation_id), self._zone(project_id)
        )

    def publications(
        self, project_id: int, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        zone = self._zone(project_id)
        return [
            _publication(item, zone)
            for item in self._dashboard.publications(
                project_id, limit=limit, offset=offset
            )
        ]

    def retry_delivery(self, project_id: int, delivery_id: int) -> dict[str, Any]:
        try:
            project_manual_delivery_retry(self._sessions, project_id).prepare(
                delivery_id
            )
        except DeliveryNotRetryable as error:
            raise ConflictError("delivery_not_retryable") from error
        run_id = self._submit_operation(
            project_id,
            OperationKind.RETRY_DELIVERY,
            delivery_id=delivery_id,
            mode="manual",
            actor="user",
        )
        return {"operation_id": run_id, "status": "running"}

    # --- внутреннее -------------------------------------------------------

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def _posts_for(self, project_id: int) -> SqlAlchemyPostRepository:
        return SqlAlchemyPostRepository(self._sessions, project_id)

    def _zone(self, project_id: int) -> ZoneInfo:
        """Контракт отдаёт время в таймзоне проекта, база хранит его в UTC."""
        return ZoneInfo(self._projects.get(project_id).timezone)

    def _channel_view(self, project_id: int) -> dict[str, Any]:
        channel = self._projects.get_channel(project_id)
        connection = channel[0] if channel is not None else None
        view = dict(channel_view(connection))
        view["checked_at"] = getattr(connection, "last_checked_at", None)
        return view

    def _project_view(self, project: ContentProject) -> dict[str, Any]:
        return {
            "id": project.id,
            "name": project.name,
            "timezone": project.timezone,
            "language": project.language,
            "audience": project.audience,
            "tone": project.configuration.tone,
            "project_prompt": project.project_prompt,
            "publication_mode": project.publication_mode,
            "generation_lead_minutes": project.generation_lead_minutes,
            "media_reuse_days": project.media_reuse_days,
            "channel": self._channel_view(project.id),
            "media": self._media.media_counts(project.id),
        }

    def _submit_scheduled(self, command: ScheduledCommand) -> None:
        self._projects.get(command.project_id)
        self._submit_operation(
            command.project_id,
            OperationKind(command.kind),
            accepted_run_id=command.operation_run_id,
            scheduled_job_id=command.job_id,
            post_id=command.post_id,
        )

    def _start_generation(self, project_id: int, slot_id: int) -> int:
        """Генерация по кнопке.

        Обработчика ещё нет: операция честно падает с generate_post_failed,
        а не висит в running. Его приносит трек агента генерации.
        """
        return self._submit_operation(
            project_id, OperationKind.GENERATE_POST, mode="manual", actor="user"
        )

    def _submit_operation(
        self,
        project_id: int,
        operation: OperationKind,
        *,
        accepted_run_id: int | None = None,
        scheduled_job_id: int | None = None,
        post_id: int | None = None,
        delivery_id: int | None = None,
        mode: str = "automatic",
        actor: str = "scheduler",
    ) -> int:
        journal = SqlAlchemyOperationRunRepository(self._sessions, project_id)
        failure_code = f"{operation.value}_failed"
        run_id = (
            accepted_run_id
            if accepted_run_id is not None
            else journal.start(operation, now=self._now(), mode=mode, actor=actor)
        )

        def run() -> None:
            try:
                if operation not in SUPPORTED_OPERATIONS:
                    raise RuntimeError("unsupported_operation")
                with open_project_publish_once(
                    self._settings,
                    project_id=project_id,
                    record_operation=False,
                    post_id=post_id,
                    delivery_id=delivery_id,
                ) as action:
                    outcome = action.execute(
                        post_id=post_id, delivery_id=delivery_id
                    ).outcome
            except BaseException:
                self._finish(journal, run_id, scheduled_job_id, code=failure_code)
                raise
            self._finish(journal, run_id, scheduled_job_id, outcome=outcome)

        try:
            self._operations.submit(project_id, operation.value, run)
        except BaseException:
            # Строку журнала оставлять running нельзя: UI опрашивает её вечно.
            self._finish(journal, run_id, None, code=failure_code)
            raise
        return run_id

    def _finish(
        self,
        journal: SqlAlchemyOperationRunRepository,
        run_id: int,
        scheduled_job_id: int | None,
        *,
        outcome: str | None = None,
        code: str | None = None,
    ) -> None:
        """Закрывает строку журнала и снимает аренду задачи планировщика."""
        now = self._now()
        try:
            if outcome is not None:
                journal.succeed(run_id, outcome=outcome, now=now)
            else:
                journal.fail(run_id, failure_code=code, now=now)
        except BaseException:
            pass
        if scheduled_job_id is not None:
            self._schedule_repository.acknowledge(
                scheduled_job_id, succeeded=outcome is not None, now=now
            )


def build_web_api() -> WebApplication:
    return WebApplication(Settings())


def _rubric(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "instructions": item.instructions,
        "enabled": item.enabled,
    }


def _at(value: datetime | None, zone: ZoneInfo) -> datetime | None:
    return None if value is None else value.astimezone(zone)


def _post_summary(item, zone: ZoneInfo) -> dict[str, Any]:
    return {
        "id": item.id,
        "status": item.status,
        "excerpt": item.excerpt,
        "char_count": item.char_count,
        "media_available": item.media_available,
        "scheduled_at": _at(item.scheduled_at, zone),
        "delivery_status": item.delivery_status,
        "created_at": _at(item.created_at, zone),
        "updated_at": _at(item.updated_at, zone),
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
            "published_at": _at(item.published_at, zone),
        }
    )
    return {
        "id": item.id,
        # Слот контент-плана появится вместе со своим треком.
        "slot_id": None,
        "status": item.status,
        "post_text": item.post_text,
        "char_count": item.char_count,
        "scheduled_at": _at(item.scheduled_at, zone),
        "media": (
            {
                "url": f"/api/projects/{project_id}/posts/{item.id}/media",
                "mime": item.media_mime,
            }
            if item.media_available
            else None
        ),
        "generation": _plain(item.generation),
        # Отчёт слоёв проверок принесёт свой трек.
        "validation": None,
        "delivery": delivery,
        "published": _at(item.published_at, zone),
        "history": [
            {
                "status": entry.status,
                "reason": entry.reason,
                "created_at": _at(entry.created_at, zone),
            }
            for entry in item.history
        ],
        "created_at": _at(item.created_at, zone),
        "updated_at": _at(item.updated_at, zone),
    }


def _operation(item, zone: ZoneInfo) -> dict[str, Any]:
    return {
        "operation_id": item.run_id,
        "purpose": item.operation,
        "status": item.status,
        "actor": item.actor,
        "mode": item.mode,
        "outcome": item.outcome,
        "result": _plain(item.result),
        "error": (
            None
            if item.failure_code is None
            else {
                "code": item.failure_code,
                "message": message_for(item.failure_code),
            }
        ),
        "started_at": _at(item.started_at, zone),
        "finished_at": _at(item.finished_at, zone),
    }


def _publication(item, zone: ZoneInfo) -> dict[str, Any]:
    return {
        "delivery_id": item.delivery_id,
        "post_id": item.post_id,
        "provider": item.provider,
        "status": item.status,
        "attempt_count": item.attempt_count,
        "message_id": item.message_id,
        "failure_code": item.failure_code,
        "failure_reason": item.failure_reason,
        "sending_started_at": _at(item.sending_started_at, zone),
        "confirmed_at": _at(item.confirmed_at, zone),
        "created_at": _at(item.created_at, zone),
        "updated_at": _at(item.updated_at, zone),
        "attempts": [
            {
                "attempt_no": attempt.attempt_no,
                "outcome": attempt.outcome,
                "code": attempt.code,
                "reason": attempt.reason,
                "message_id": attempt.message_id,
                "started_at": _at(attempt.started_at, zone),
                "finished_at": _at(attempt.finished_at, zone),
            }
            for attempt in item.attempts
        ],
    }


def _plain(value: object) -> dict[str, Any]:
    """Снимает MappingProxyType, который не переживает сериализацию JSON."""
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    return {}


def _plain_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _plain(value)
    if isinstance(value, (tuple, list)):
        return [_plain_value(item) for item in value]
    return value
