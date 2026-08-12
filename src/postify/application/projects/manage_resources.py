from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
class ManageProjectResources:
    """Application boundary for project-scoped settings resources."""

    def __init__(
        self,
        repository,
        source_registry,
        channel_registry,
        *,
        cipher,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._sources = source_registry
        self._channels = channel_registry
        self._cipher = cipher
        self._clock = clock

    def list(self, project_id: int, resource: str):
        self._project(project_id)
        return self._repository.list_resources(project_id, resource)

    def create(self, project_id: int, resource: str, payload: dict[str, object]):
        self._project(project_id)
        return self._repository.create_resource(
            project_id, resource, self._validated(resource, payload), self._clock()
        )

    def update(
        self, project_id: int, resource: str, resource_id: int, payload: dict[str, object]
    ):
        self._project(project_id)
        return self._repository.update_resource(
            project_id,
            resource,
            resource_id,
            self._validated(resource, payload),
            self._clock(),
        )

    def delete(self, project_id: int, resource: str, resource_id: int) -> None:
        self._project(project_id)
        self._repository.delete_resource(project_id, resource, resource_id)

    def remove_channel_secret(self, project_id: int, channel_id: int):
        self._project(project_id)
        return self._repository.remove_channel_secret(
            project_id, channel_id, self._clock()
        )

    def _project(self, project_id: int) -> None:
        self._repository.get(project_id)

    def _validated(self, resource: str, payload: dict[str, object]) -> dict[str, object]:
        if resource == "sources":
            return self._source(payload)
        if resource == "channels":
            return self._channel(payload)
        if resource in {"ctas", "routes"}:
            return payload
        raise ValueError("unknown_resource")

    def _source(self, payload: dict[str, object]) -> dict[str, object]:
        values = dict(payload)
        provider = values.get("provider")
        configuration = values.get("configuration")
        values["configuration"] = self._sources.validate(provider, configuration)
        return values

    def _channel(self, payload: dict[str, object]) -> dict[str, object]:
        values = dict(payload)
        provider = values.get("provider")
        values["configuration"] = self._channels.validate(
            provider, values.get("configuration")
        )
        token = values.pop("token", None)
        if token is not None:
            if self._cipher is None:
                raise RuntimeError("secret_storage_unavailable")
            values["encrypted_secret"] = self._cipher.encrypt(token)
        return values
