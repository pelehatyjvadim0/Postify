from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import sessionmaker

from postify.adapters.channels.registry import ChannelProviderRegistry
from postify.adapters.sources.registry import SourceProviderRegistry
from postify.adapters.http.public_url_policy import PublicHttpUrlPolicy
from postify.adapters.media.local_media_provider import LocalMediaProvider
from postify.application.content.manual_operations import (
    ManualContentOperations,
)
from postify.application.delivery.manual_operations import (
    DeliveryNotRetryable,
    ManualDeliveryRetry,
)
from postify.application.observability.record_operation import (
    content_operation_metadata,
)
from postify.application.projects.bootstrap_project import BootstrapProject
from postify.application.projects.manage_project import ManageProject
from postify.application.projects.manage_resources import ManageProjectResources
from postify.application.projects.manage_schedule import ManageProjectSchedule
from postify.application.projects.check_channel import CheckChannel
from postify.application.scheduling.project_scheduler import (
    ProjectScheduler,
    ScheduledCommand,
)
from postify.bootstrap import (
    open_project_publish_once,
    open_project_run_once,
    project_manual_content_operations,
    project_manual_delivery_retry,
    project_review_content,
)
from postify.config import Settings, TelegramSettings
from postify.domain.observability.models import OperationKind
from postify.domain.content.models import (
    ExecutionActor,
    ExecutionContext,
    ExecutionMode,
    ExecutionPurpose,
)
from postify.infrastructure.database.engine import create_engine_from_settings
from postify.infrastructure.repositories.sqlalchemy_dashboard import SqlAlchemyDashboardRepository
from postify.infrastructure.repositories.sqlalchemy_projects import SqlAlchemyProjectRepository
from postify.infrastructure.repositories.sqlalchemy_observability import SqlAlchemyOperationRunRepository
from postify.infrastructure.repositories.sqlalchemy_schedule import (
    SqlAlchemyScheduleRepository,
)
from postify.infrastructure.security.secrets import SecretCipher


class BoundedOperations:
    """Limits concurrent UI operations and atomically rejects duplicate kinds."""

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="postify-web")
        self._capacity = max_workers
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
    """Composition facade; HTTP routes only map transport into these actions/queries."""

    def __init__(self, settings: Settings, telegram: TelegramSettings | None) -> None:
        self._settings = settings
        self._telegram = telegram
        self._engine = create_engine_from_settings(settings)
        self._sessions = sessionmaker(self._engine)
        self._projects = SqlAlchemyProjectRepository(self._sessions)
        self._dashboard = SqlAlchemyDashboardRepository(self._sessions)
        self._operations = BoundedOperations()
        self._schedule_repository = SqlAlchemyScheduleRepository(self._sessions)
        self._scheduler = ProjectScheduler(
            self._schedule_repository, self._submit_scheduled
        )
        self._cipher = (
            SecretCipher(settings.postify_secret_key.get_secret_value())
            if settings.postify_secret_key is not None
            else None
        )
        self._source_providers = SourceProviderRegistry()
        self._channel_providers = ChannelProviderRegistry()
        BootstrapProject(
            self._projects,
            self._source_providers,
            self._channel_providers,
            cipher=self._cipher,
            clock=lambda: datetime.now(UTC),
        ).execute(settings, telegram)
        self._resources = ManageProjectResources(
            self._projects,
            self._source_providers,
            self._channel_providers,
            cipher=self._cipher,
            clock=lambda: datetime.now(UTC),
        )

    def bootstrap(self) -> dict[str, object]:
        project = self._projects.active_project()
        if project is None:
            raise LookupError(1)
        return {
            "activeProject": _project(project),
            "providers": {
                "sources": self._source_providers.catalog(),
                "channels": self._channel_providers.catalog(),
            },
        }

    def scheduler_tick(self) -> tuple[ScheduledCommand, ...]:
        return self._scheduler.tick(datetime.now(UTC))

    def close(self) -> None:
        self._operations.close()
        self._engine.dispose()

    def materials(self, project_id: int, **filters: object) -> dict[str, object]:
        self._projects.get(project_id)
        return {"items": [_values(item) for item in self._dashboard.materials(project_id, **filters)]}

    def packages(self, project_id: int, **filters: object) -> dict[str, object]:
        self._projects.get(project_id)
        return {"items": [_values(item) for item in self._dashboard.packages(project_id, **filters)]}

    def package(self, project_id: int, package_id: int) -> dict[str, object]:
        project = self._projects.get(project_id)
        channels = {item["id"]: item for item in self._resources.list(project_id, "channels")}
        routes = [
            {"id": item["id"], "name": channels[item["channel_id"]]["name"]}
            for item in self._resources.list(project_id, "routes")
            if item["enabled"] and item["channel_id"] in channels
            and channels[item["channel_id"]]["enabled"]
        ]
        return _values(self._dashboard.package(project_id, package_id)) | {
            "timezone": project.timezone, "routes": routes,
        }

    def save_plan(self, project_id: int, package_id: int, *, scheduled_at: datetime, route_id: int):
        self._projects.get(project_id)
        with self._review(project_id) as action:
            action.save_plan(package_id, scheduled_at=scheduled_at, route_id=route_id)
        return self.package(project_id, package_id)

    def approve(self, project_id: int, package_id: int) -> dict[str, object]:
        with self._review(project_id) as action:
            action.approve(package_id)
        return _values(self._dashboard.package(project_id, package_id))

    def reject(self, project_id: int, package_id: int) -> dict[str, object]:
        with self._review(project_id) as action:
            action.reject(package_id)
        return _values(self._dashboard.package(project_id, package_id))

    def queue(self, project_id: int) -> dict[str, object]:
        project = self._projects.get(project_id)
        day, _, _ = _day_boundaries(project.timezone)
        return {"items": [_values(item) for item in self._dashboard.queue(project_id, day)]}

    def publications(self, project_id: int, **filters: object) -> dict[str, object]:
        self._projects.get(project_id)
        return {"items": [_values(item) for item in self._dashboard.publications(project_id, **filters)]}

    def operations(self, project_id: int, **filters: object) -> dict[str, object]:
        project = self._projects.get(project_id)
        return {
            "items": [
                _values(item)
                for item in self._dashboard.operations(project_id, **filters)
            ],
        }

    def operation(self, project_id: int, operation_run_id: int) -> dict[str, object]:
        self._projects.get(project_id)
        return _values(self._dashboard.operation(project_id, operation_run_id))

    def run_once(self, project_id: int) -> dict[str, object]:
        self._projects.get(project_id)
        self._submit_operation(
            project_id,
            "run_once",
            context=ExecutionContext(
                mode=ExecutionMode.MANUAL,
                actor=ExecutionActor.UI,
                purpose=ExecutionPurpose.RUN_ONCE,
            ),
        )
        return {"status": "accepted"}

    def manual_search(self, project_id: int) -> dict[str, object]:
        self._projects.get(project_id)
        context = ExecutionContext(
            mode=ExecutionMode.MANUAL,
            actor=ExecutionActor.UI,
            purpose=ExecutionPurpose.MANUAL_SEARCH,
        )
        run_id = self._submit_operation(project_id, "manual_search", context=context)
        return {"status": "accepted", "operationRunId": run_id}

    def retry_analysis(self, project_id: int, attempt_id: int) -> dict[str, object]:
        self._projects.get(project_id)
        context = self._manual_content_for(project_id).retry_analysis(attempt_id)
        run_id = self._submit_operation(project_id, "retry_analysis", context=context)
        return {"status": "accepted", "operationRunId": run_id}

    def return_to_analysis(self, project_id: int, package_id: int) -> dict[str, object]:
        self._projects.get(project_id)
        context = self._manual_content_for(project_id).return_to_analysis(package_id)
        run_id = self._submit_operation(project_id, "return_to_analysis", context=context)
        return {"status": "accepted", "operationRunId": run_id}

    def regenerate_post(self, project_id: int, package_id: int) -> dict[str, object]:
        self._projects.get(project_id)
        context = self._manual_content_for(project_id).regenerate_post(package_id)
        run_id = self._submit_operation(project_id, "regenerate_post", context=context)
        return {"status": "accepted", "operationRunId": run_id}

    def retry_delivery(self, project_id: int, delivery_id: int) -> dict[str, object]:
        self._projects.get(project_id)
        try:
            route_id, context = self._manual_delivery_for(project_id).prepare(delivery_id)
        except DeliveryNotRetryable as error:
            from postify.web.errors import ConflictError

            raise ConflictError("delivery_not_retryable") from error
        run_id = self._submit_operation(
            project_id,
            "retry_delivery",
            route_id=route_id,
            delivery_id=delivery_id,
            context=context,
        )
        return {"status": "accepted", "operationRunId": run_id}

    def settings(self, project_id: int) -> dict[str, object]:
        return {
            "project": _project(self._projects.get(project_id)),
            "sources": self._resources.list(project_id, "sources"),
            "formats": self._formats(project_id),
            "channels": self._resources.list(project_id, "channels"),
            "routes": self._resources.list(project_id, "routes"),
        }

    def update_settings(self, project_id: int, section: str, payload: dict[str, object]) -> dict[str, object]:
        if section == "schedule":
            return ManageProjectSchedule(self._projects).update(
                project_id, payload, now=datetime.now(UTC)
            )
        return _project(ManageProject(self._projects).update(project_id, section, payload, now=datetime.now(UTC)))

    def resources(self, project_id: int, resource: str) -> dict[str, object]:
        return {"items": self._resources.list(project_id, resource)}

    def create_resource(self, project_id: int, resource: str, payload: dict[str, object]) -> dict[str, object]:
        return self._resources.create(project_id, resource, payload)

    def update_resource(self, project_id: int, resource: str, resource_id: int, payload: dict[str, object]) -> dict[str, object]:
        return self._resources.update(project_id, resource, resource_id, payload)

    def delete_resource(self, project_id: int, resource: str, resource_id: int) -> None:
        self._resources.delete(project_id, resource, resource_id)

    def check_channel(self, project_id: int, channel_id: int) -> dict[str, object]:
        from postify.adapters.channels.telegram_check import TelegramChannelChecker

        with httpx.Client() as client:
            return CheckChannel(
                self._projects,
                self._cipher,
                TelegramChannelChecker(client),
                clock=lambda: datetime.now(UTC),
            ).execute(project_id, channel_id)

    def remove_channel_secret(
        self, project_id: int, channel_id: int
    ) -> dict[str, object]:
        return self._resources.remove_channel_secret(project_id, channel_id)

    def package_media(self, project_id: int, package_id: int) -> tuple[bytes, str]:
        media_path, media_mime = self._dashboard.package_media_path(
            project_id, package_id
        )
        try:
            return open(media_path, "rb").read(), media_mime
        except OSError:
            raise LookupError(package_id) from None

    def _formats(self, project_id: int) -> list[dict[str, object]]:
        from postify.infrastructure.database.models import ContentFormatModel
        from sqlalchemy import select

        with self._sessions() as session:
            return [
                {"id": row.id, "name": row.name, "kind": row.kind, "instructions": row.instructions, "enabled": row.enabled}
                for row in session.scalars(select(ContentFormatModel).where(ContentFormatModel.project_id == project_id)).all()
            ]

    def _manual_content_for(self, project_id: int) -> ManualContentOperations:
        return project_manual_content_operations(self._sessions, project_id)

    def _manual_delivery_for(self, project_id: int) -> ManualDeliveryRetry:
        return project_manual_delivery_retry(self._sessions, project_id)

    @contextmanager
    def _review(self, project_id: int):
        yield project_review_content(
            self._sessions,
            project_id,
            LocalMediaProvider(self._settings.content_media_dir),
            clock=lambda: datetime.now(UTC),
        )

    def _run_once(self, project_id: int, *, context: ExecutionContext):
        with open_project_run_once(
            self._settings,
            project_id=project_id,
            record_operation=False,
            context=context,
        ) as action:
            return action.execute()

    def _submit_scheduled(self, command: ScheduledCommand) -> None:
        self._projects.get(command.project_id)
        self._submit_operation(
            command.project_id,
            command.kind,
            accepted_run_id=command.operation_run_id,
            route_id=command.route_id,
            scheduled_job_id=command.job_id,
            package_id=command.package_id,
            context=ExecutionContext(
                mode=ExecutionMode.AUTOMATIC,
                actor=ExecutionActor.SCHEDULER,
                purpose=ExecutionPurpose(command.kind),
            ),
        )

    def _submit_operation(
        self,
        project_id: int,
        kind: str,
        *,
        accepted_run_id: int | None = None,
        route_id: int | None = None,
        scheduled_job_id: int | None = None,
        package_id: int | None = None,
        delivery_id: int | None = None,
        context: ExecutionContext,
    ) -> int:
        operation_kind = OperationKind(kind)
        journal = SqlAlchemyOperationRunRepository(
            self._sessions, project_id=project_id
        )
        run_id = (
            accepted_run_id
            if accepted_run_id is not None
            else journal.start(
                operation_kind, now=datetime.now(UTC),
                mode=(context.mode if context else "automatic"),
                actor=(context.actor if context else "scheduler"),
            )
        )

        def operation() -> None:
            metadata = {
                "codex_model": None,
                "codex_reasoning_effort": None,
                "materials_taken": 0,
                "packages_created": 0,
            }
            try:
                if kind in {"run_once", "manual_search"}:
                    result = self._run_once(project_id, context=context)
                    content_result = result.content_result
                    metadata = content_operation_metadata(content_result)
                    if (
                        context.is_manual
                        and content_result is not None
                        and content_result.failed
                    ):
                        raise RuntimeError("manual_content_failed")
                    outcome = "completed"
                elif kind in {"retry_analysis", "return_to_analysis", "regenerate_post"}:
                    from postify.bootstrap import open_project_run_once
                    with open_project_run_once(
                        self._settings, project_id=project_id, record_operation=False,
                        context=context,
                    ) as action:
                        result = action.process_content()
                    metadata = content_operation_metadata(result)
                    if result.failed:
                        raise RuntimeError("manual_content_failed")
                    outcome = "completed" if result.packages_created else "empty"
                elif kind in {"publish_once", "retry_delivery"}:
                    with open_project_publish_once(
                        self._settings,
                        project_id=project_id,
                        route_id=route_id,
                        record_operation=False,
                        package_id=package_id,
                        delivery_id=delivery_id,
                    ) as action:
                        outcome = action.execute(package_id=package_id, delivery_id=delivery_id).outcome
                else:
                    raise ValueError("unsupported_operation")
            except BaseException:
                try:
                    journal.fail(
                        run_id,
                        failure_code=f"{kind}_failed",
                        now=datetime.now(UTC),
                        **metadata,
                    )
                except BaseException:
                    pass
                if scheduled_job_id is not None:
                    self._schedule_repository.acknowledge(
                        scheduled_job_id, succeeded=False, now=datetime.now(UTC)
                    )
                raise
            journal.succeed(
                run_id, outcome=outcome, now=datetime.now(UTC), **metadata
            )
            if scheduled_job_id is not None:
                self._schedule_repository.acknowledge(
                    scheduled_job_id, succeeded=True, now=datetime.now(UTC)
                )

        try:
            self._operations.submit(project_id, kind, operation)
        except BaseException:
            try:
                journal.fail(
                    run_id,
                    failure_code=f"{kind}_failed",
                    now=datetime.now(UTC),
                )
            except BaseException:
                pass
            raise
        return run_id


def build_web_api() -> WebApplication:
    settings = Settings()
    try:
        telegram: TelegramSettings | None = TelegramSettings()
    except Exception:
        telegram = None
    return WebApplication(settings, telegram)


def _values(value: object) -> dict[str, object]:
    if is_dataclass(value):
        return {
            field.name: _plain_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return value
    return {"result": value}


def _plain_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_value(item) for item in value]
    if is_dataclass(value):
        return _values(value)
    return value


def _project(value) -> dict[str, object]:
    result = _values(value)
    result["configuration"] = _values(value.configuration)
    return result


def _day_boundaries(timezone: str):
    local = datetime.now(UTC).astimezone(ZoneInfo(timezone))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.date(), start, start + timedelta(days=1)
