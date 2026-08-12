from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
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
from postify.application.projects.manage_project import ManageProject
from postify.application.projects.manage_resources import ManageProjectResources
from postify.application.projects.manage_schedule import ManageProjectSchedule
from postify.application.projects.check_channel import CheckChannel
from postify.bootstrap import open_publish_once, open_run_once
from postify.config import Settings, TelegramSettings
from postify.infrastructure.database.engine import create_engine_from_settings
from postify.infrastructure.repositories.sqlalchemy_content import SqlAlchemyContentRepository
from postify.infrastructure.repositories.sqlalchemy_dashboard import SqlAlchemyDashboardRepository
from postify.infrastructure.repositories.sqlalchemy_projects import SqlAlchemyProjectRepository
from postify.infrastructure.security.secrets import SecretCipher


class BoundedOperations:
    """Limits concurrent UI operations and atomically rejects duplicate kinds."""

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="postify-web")
        self._capacity = max_workers
        self._active: set[tuple[int, str]] = set()
        self._lock = Lock()

    def submit(self, project_id: int, kind: str, operation) -> None:
        key = (project_id, kind)
        with self._lock:
            if key in self._active or len(self._active) >= self._capacity:
                raise RuntimeError("operation_busy")
            self._active.add(key)

        def run() -> None:
            try:
                operation()
            finally:
                with self._lock:
                    self._active.discard(key)

        self._executor.submit(run)


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
        self._cipher = (
            SecretCipher(settings.postify_secret_key.get_secret_value())
            if settings.postify_secret_key is not None
            else None
        )
        self._source_providers = SourceProviderRegistry()
        self._channel_providers = ChannelProviderRegistry()
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

    def dashboard(self, project_id: int) -> dict[str, object]:
        project = self._projects.get(project_id)
        day, start, end = _day_boundaries(project.timezone)
        return _values(ShowDashboard(self._dashboard).execute(project_id, day, start, end))

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
        self._projects.get(project_id)
        return {"items": [_values(item) for item in self._dashboard.operations(project_id, **filters)]}

    def run_once(self, project_id: int) -> dict[str, object]:
        self._projects.get(project_id)
        self._operations.submit(
            project_id, "run_once", lambda: self._run_once(project_id)
        )
        return {"status": "accepted"}

    def publish_once(self, project_id: int) -> dict[str, object]:
        self._projects.get(project_id)
        if self._telegram is None:
            raise RuntimeError("service_unavailable")
        with open_publish_once(self._settings, self._telegram) as action:
            return _values(action.execute())

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
        media_path = self._dashboard.package_media_path(project_id, package_id)
        try:
            return open(media_path, "rb").read(), "image/jpeg"
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
        with open_run_once(self._settings, project_id=project_id) as action:
            action.execute()


def build_web_api() -> WebApplication:
    settings = Settings()
    try:
        telegram: TelegramSettings | None = TelegramSettings()
    except Exception:
        telegram = None
    return WebApplication(settings, telegram)


def _values(value: object) -> dict[str, object]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return {"result": value}


def _project(value) -> dict[str, object]:
    result = _values(value)
    result["configuration"] = _values(value.configuration)
    return result


def _day_boundaries(timezone: str):
    local = datetime.now(UTC).astimezone(ZoneInfo(timezone))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.date(), start, start + timedelta(days=1)
