from __future__ import annotations

from datetime import UTC, datetime

import pytest

from postify.application.projects.manage_resources import ManageProjectResources


NOW = datetime(2026, 8, 12, 10, tzinfo=UTC)


class Repository:
    def __init__(self) -> None:
        self.created: tuple[object, ...] | None = None
        self.removed_secret: tuple[object, ...] | None = None
        self.validated_route: tuple[object, ...] | None = None

    def get(self, project_id: int):
        if project_id != 1:
            raise LookupError(project_id)
        return object()

    def create_resource(self, project_id: int, resource: str, payload: dict[str, object], now):
        self.created = (project_id, resource, payload, now)
        return {"id": 7, **payload}

    def remove_channel_secret(self, project_id: int, channel_id: int, now):
        self.removed_secret = (project_id, channel_id, now)
        return {"id": channel_id, "secretConfigured": False}

    def validate_route_references(
        self, project_id: int, format_id: int, channel_id: int, cta_id: int | None
    ) -> None:
        self.validated_route = (project_id, format_id, channel_id, cta_id)


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


def test_remove_channel_secret_is_an_explicit_action() -> None:
    # Break caught: an empty edit silently removes credentials or secret removal deletes the channel.
    repository = Repository()
    action = ManageProjectResources(
        repository, Sources(), object(), cipher=None, clock=lambda: NOW
    )

    result = action.remove_channel_secret(1, 7)

    assert result == {"id": 7, "secretConfigured": False}
    assert repository.removed_secret == (1, 7, NOW)


def test_cta_is_domain_validated_before_persistence() -> None:
    # Поломка review: CTA payload шёл в SQL мимо CallToAction.
    repository = Repository()
    action = ManageProjectResources(
        repository, Sources(), object(), cipher=None, clock=lambda: NOW
    )

    with pytest.raises(ValueError, match="HTTP"):
        action.create(
            1,
            "ctas",
            {
                "name": "Custom",
                "text": "Read",
                "link_mode": "custom",
                "custom_url": "ftp://private.example/file",
                "enabled": True,
            },
        )

    assert repository.created is None


def test_route_is_domain_validated_and_references_are_project_scoped() -> None:
    # Поломка review: project 1 route мог ссылаться на project 2 resources.
    repository = Repository()
    action = ManageProjectResources(
        repository, Sources(), object(), cipher=None, clock=lambda: NOW
    )

    action.create(
        1,
        "routes",
        {
            "format_id": 11,
            "channel_id": 12,
            "cta_id": 13,
            "enabled": True,
        },
    )

    assert repository.validated_route == (1, 11, 12, 13)
    assert repository.created == (
        1,
        "routes",
        {"format_id": 11, "channel_id": 12, "cta_id": 13, "enabled": True},
        NOW,
    )
