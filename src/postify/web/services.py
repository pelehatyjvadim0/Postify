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
from postify.application.content.review_content import ReviewContent
from postify.application.dashboard.show_dashboard import ShowDashboard
from postify.application.observability.show_status import (
    RuntimeSnapshot,
    ShowOperationalStatus,
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
from postify.bootstrap import open_project_publish_once, open_project_run_once
from postify.config import Settings, TelegramSettings
from postify.domain.observability.models import OperationKind
from postify.infrastructure.database.engine import create_engine_from_settings
from postify.infrastructure.repositories.sqlalchemy_content import SqlAlchemyContentRepository
from postify.infrastructure.repositories.sqlalchemy_dashboard import SqlAlchemyDashboardRepository
from postify.infrastructure.repositories.sqlalchemy_projects import SqlAlchemyProjectRepository
from postify.infrastructure.repositories.sqlalchemy_observability import (
    SqlAlchemyOperationalStatusRepository,
    SqlAlchemyOperationRunRepository,
)
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
        self._scheduler = ProjectScheduler(
            SqlAlchemyScheduleRepository(self._sessions), self._submit_scheduled
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

    def dashboard(self, project_id: int) -> dict[str, object]:
        project = self._projects.get(project_id)
        day, start, end = _day_boundaries(project.timezone)
        return _values(
            ShowDashboard(self._dashboard).execute(project_id, day, start, end)
        ) | self._operational(project)

    def materials(self, project_id: int, **filters: object) -> dict[str, object]:
        self._projects.get(project_id)
        return {"items": [_values(item) for item in self._dashboard.materials(project_id, **filters)]}

    def packages(self, project_id: int, **filters: object) -> dict[str, object]:
        self._projects.get(project_id)
        return {"items": [_values(item) for item in self._dashboard.packages(project_id, **filters)]}

    def package(self, project_id: int, package_id: int) -> dict[str, object]:
        self._projects.get(project_id)
        return _values(self._dashboard.package(project_id, package_id))

    def approve(self, project_id: int, package_id: int) -> dict[str, object]:
        with self._review(project_id) as action:
            return _values(action.approve(package_id))

    def reject(self, project_id: int, package_id: int, reason: str) -> dict[str, object]:
        with self._review(project_id) as action:
            return _values(action.reject(package_id, reason=reason))

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
            "operational": self._operational(project),
        }

    def run_once(self, project_id: int) -> dict[str, object]:
        self._projects.get(project_id)
        self._submit_operation(project_id, "run_once")
        return {"status": "accepted"}

    def publish_once(self, project_id: int) -> dict[str, object]:
        self._projects.get(project_id)
        self._submit_operation(project_id, "publish_once")
        return {"status": "accepted"}

    def settings(self, project_id: int) -> dict[str, object]:
        return {
            "project": _project(self._projects.get(project_id)),
            "sources": self._resources.list(project_id, "sources"),
            "formats": self._formats(project_id),
            "ctas": self._resources.list(project_id, "ctas"),
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

    def _operational(self, project) -> dict[str, object]:
        configuration = project.configuration
        report = ShowOperationalStatus(
            SqlAlchemyOperationalStatusRepository(
                self._sessions, project_id=project.id
            ),
            timezone=ZoneInfo(project.timezone),
            daily_target=configuration.daily_package_limit,
            analysis_limit=configuration.daily_analysis_limit,
            package_limit=configuration.daily_package_limit,
            clock=lambda: datetime.now(UTC),
        ).execute(RuntimeSnapshot())
        return {
            "coverage": report.coverage,
            "deficit": report.deficit,
            "deficit_reasons": list(report.deficit_reasons),
            "ready_delivery_ids": list(report.snapshot.delivery_ready_ids),
            "runtime": {
                "database": "available",
                "scheduler": "active",
            },
            "signals": [_values(item) for item in report.signals],
            "recent_operations": [
                _values(item) for item in report.latest_operation_runs
            ],
        }

    @contextmanager
    def _review(self, project_id: int):
        client = httpx.Client()
        try:
            yield ReviewContent(
                SqlAlchemyContentRepository(self._sessions, project_id=project_id),
                LocalMediaProvider(client, self._settings.content_media_dir, self._settings.content_media_max_bytes, None, url_policy=PublicHttpUrlPolicy()),
                clock=lambda: datetime.now(UTC),
            )
        finally:
            client.close()

    def _run_once(self, project_id: int) -> None:
        with open_project_run_once(
            self._settings,
            project_id=project_id,
            record_operation=False,
        ) as action:
            action.execute()

    def _publish_once(self, project_id: int) -> None:
        with open_project_publish_once(
            self._settings,
            project_id=project_id,
            record_operation=False,
        ) as action:
            action.execute()

    def _submit_scheduled(self, command: ScheduledCommand) -> None:
        self._projects.get(command.project_id)
        self._submit_operation(
            command.project_id,
            command.kind,
            accepted_run_id=command.operation_run_id,
        )

    def _submit_operation(
        self,
        project_id: int,
        kind: str,
        *,
        accepted_run_id: int | None = None,
    ) -> None:
        operation_kind = OperationKind(kind)
        journal = SqlAlchemyOperationRunRepository(
            getattr(self, "_sessions", None), project_id=project_id
        )
        run_id = (
            accepted_run_id
            if accepted_run_id is not None
            else journal.start(operation_kind, now=datetime.now(UTC))
        )

        def operation() -> None:
            try:
                if kind == "run_once":
                    self._run_once(project_id)
                    outcome = "completed"
                else:
                    with open_project_publish_once(
                        self._settings,
                        project_id=project_id,
                        record_operation=False,
                    ) as action:
                        outcome = action.execute().outcome
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
            journal.succeed(run_id, outcome=outcome, now=datetime.now(UTC))

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
