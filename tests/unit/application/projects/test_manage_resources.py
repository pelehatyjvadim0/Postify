from __future__ import annotations

from datetime import UTC, datetime

from postify.application.projects.manage_resources import ManageProjectResources


NOW = datetime(2026, 8, 12, 10, tzinfo=UTC)


class Repository:
    def __init__(self) -> None:
        self.created: tuple[object, ...] | None = None

    def get(self, project_id: int):
        if project_id != 1:
            raise LookupError(project_id)
        return object()

    def create_resource(self, project_id: int, resource: str, payload: dict[str, object], now):
        self.created = (project_id, resource, payload, now)
        return {"id": 7, **payload}


class Sources:
    def validate(self, provider: str, configuration: object) -> dict[str, object]:
        assert provider == "hn_algolia"
        return {"query": "python", "tags": "story", "hits": 10, "url": "https://hn.test"}


def test_create_source_validates_provider_before_persisting() -> None:
    # Break caught: source configuration bypasses its provider registry before it reaches persistence.
    repository = Repository()
    action = ManageProjectResources(repository, Sources(), object(), cipher=None, clock=lambda: NOW)

    result = action.create(
        1,
        "sources",
        {
            "provider": "hn_algolia",
            "name": "HN",
            "enabled": True,
            "configuration": {"query": "ignored"},
            "schedule": "0 * * * *",
        },
    )

    assert result["id"] == 7
    assert repository.created == (
        1,
        "sources",
        {
            "provider": "hn_algolia",
            "name": "HN",
            "enabled": True,
            "configuration": {"query": "python", "tags": "story", "hits": 10, "url": "https://hn.test"},
            "schedule": "0 * * * *",
        },
        NOW,
    )
