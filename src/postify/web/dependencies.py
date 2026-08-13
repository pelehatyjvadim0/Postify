from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class WebApi(Protocol):
    def scheduler_tick(self) -> object: ...

    def bootstrap(self) -> dict[str, Any]: ...

    def dashboard(self, project_id: int) -> dict[str, Any]: ...

    def materials(self, project_id: int, **filters: object) -> dict[str, Any]: ...

    def packages(self, project_id: int, **filters: object) -> dict[str, Any]: ...

    def package(self, project_id: int, package_id: int) -> dict[str, Any]: ...

    def approve(self, project_id: int, package_id: int) -> dict[str, Any]: ...

    def reject(self, project_id: int, package_id: int, reason: str) -> dict[str, Any]: ...

    def queue(self, project_id: int) -> dict[str, Any]: ...

    def publications(self, project_id: int, **filters: object) -> dict[str, Any]: ...

    def operations(self, project_id: int, **filters: object) -> dict[str, Any]: ...

    def run_once(self, project_id: int) -> dict[str, Any]: ...

    def publish_once(self, project_id: int) -> dict[str, Any]: ...

    def settings(self, project_id: int) -> dict[str, Any]: ...

    def update_settings(
        self, project_id: int, section: str, payload: dict[str, object]
    ) -> dict[str, Any]: ...

    def resources(self, project_id: int, resource: str) -> dict[str, Any]: ...

    def create_resource(
        self, project_id: int, resource: str, payload: dict[str, object]
    ) -> dict[str, Any]: ...

    def update_resource(
        self,
        project_id: int,
        resource: str,
        resource_id: int,
        payload: dict[str, object],
    ) -> dict[str, Any]: ...

    def delete_resource(self, project_id: int, resource: str, resource_id: int) -> None: ...

    def check_channel(self, project_id: int, channel_id: int) -> dict[str, Any]: ...

    def remove_channel_secret(
        self, project_id: int, channel_id: int
    ) -> dict[str, Any]: ...

    def package_media(self, project_id: int, package_id: int) -> tuple[bytes, str]: ...


@dataclass(frozen=True, slots=True)
class WebContainer:
    """Explicit web boundary: tests may inject a complete application facade."""

    api: WebApi


def build_default_container() -> WebContainer:
    from postify.web.services import build_web_api

    return WebContainer(api=build_web_api())
