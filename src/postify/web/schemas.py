from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from postify.domain.observability.models import (
    OperationActor,
    OperationKind,
    OperationMode,
    OperationStatus,
)
from postify.domain.projects.cron import normalize_cron


class RequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponseSchema(BaseModel):
    """Явный allowlist для outbound-контрактов."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class BootstrapProjectResponse(ResponseSchema):
    id: int
    name: str
    topic: str | None = None
    language: str | None = None
    audience: str | None = None
    timezone: str | None = None
    configuration: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProviderFieldResponse(ResponseSchema):
    name: str
    label: str
    input_type: str = Field(alias="type", serialization_alias="type")
    required: bool
    protocol: str | None = None
    minimum: int | None = Field(default=None, alias="min", serialization_alias="min")
    maximum: int | None = Field(default=None, alias="max", serialization_alias="max")


class CredentialDescriptorResponse(ResponseSchema):
    name: str
    label: str
    input_type: str


class ProviderCatalogEntryResponse(ResponseSchema):
    code: str
    label: str
    fields: tuple[ProviderFieldResponse, ...]
    credential: CredentialDescriptorResponse | None = None


class ProviderCatalogResponse(ResponseSchema):
    sources: tuple[ProviderCatalogEntryResponse, ...]
    channels: tuple[ProviderCatalogEntryResponse, ...]


class BootstrapResponse(ResponseSchema):
    csrf_token: str = Field(alias="csrfToken", serialization_alias="csrfToken")
    active_project: BootstrapProjectResponse = Field(
        alias="activeProject", serialization_alias="activeProject"
    )
    providers: ProviderCatalogResponse


class OperationPollingResponse(ResponseSchema):
    run_id: int = Field(gt=0)
    kind: OperationKind
    mode: OperationMode
    actor: OperationActor
    status: OperationStatus
    outcome: Literal[
        "completed",
        "empty",
        "published",
        "cleanup_completed",
        "cleanup_pending",
        "retryable",
        "failed",
        "uncertain",
    ] | None = None
    failure_code: Literal[
        "run_once_failed",
        "publish_once_failed",
        "load_more_failed",
        "retry_analysis_failed",
        "return_to_analysis_failed",
        "regenerate_post_failed",
        "replace_media_failed",
        "publish_now_failed",
        "retry_delivery_failed",
        "manual_search_failed",
    ] | None = None
    codex_model: str | None = Field(default=None, min_length=1)
    codex_reasoning_effort: Literal[
        "low", "medium", "high", "xhigh", "max"
    ] | None = None
    materials_taken: int = Field(ge=0)
    packages_created: int = Field(ge=0)
    started_at: datetime
    finished_at: datetime | None = None


class MainSettingsRequest(RequestSchema):
    name: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    language: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    timezone: str = Field(min_length=1)


class ConfigurationSettingsRequest(RequestSchema):
    selection_rules: tuple[str, ...] | None = None
    topic_terms: tuple[str, ...] | None = None
    topic_exclusion_terms: tuple[str, ...] | None = None
    advertising_terms: tuple[str, ...] | None = None
    hiring_terms: tuple[str, ...] | None = None
    technical_release_terms: tuple[str, ...] | None = None
    practical_terms: tuple[str, ...] | None = None
    selection_freshness_days: int | None = Field(default=None, gt=0)
    daily_analysis_limit: int | None = Field(default=None, gt=0)
    daily_package_limit: int | None = Field(default=None, gt=0)
    priority_freshness_days: int | None = Field(default=None, gt=0)
    fresh_share_percent: int | None = Field(default=None, ge=0, le=100)
    reserve_share_percent: int | None = Field(default=None, ge=0, le=100)
    review_required: bool | None = None
    article_max_bytes: int | None = Field(default=None, gt=0)
    media_max_bytes: int | None = Field(default=None, gt=0)
    analysis_timeout_seconds: int | None = Field(default=None, gt=0)
    analysis_model: str | None = Field(default=None, min_length=1)
    analysis_reasoning_effort: Literal[
        "low", "medium", "high", "xhigh", "max"
    ] | None = None


class SourceRequest(RequestSchema):
    provider: str = Field(min_length=1)
    name: str = Field(min_length=1)
    enabled: bool
    configuration: dict[str, Any]
    schedule: str = Field(min_length=1)

    @field_validator("schedule")
    @classmethod
    def valid_cron(cls, value: str) -> str:
        return normalize_cron(value)


class ChannelRequest(RequestSchema):
    provider: str = Field(min_length=1)
    name: str = Field(min_length=1)
    enabled: bool
    configuration: dict[str, Any]
    token: str | None = Field(default=None, min_length=1)


class CtaRequest(RequestSchema):
    name: str = Field(min_length=1)
    text: str = Field(min_length=1)
    link_mode: Literal["none", "source", "custom"]
    custom_url: HttpUrl | None = None
    enabled: bool


class PublicationScheduleRequest(RequestSchema):
    autopublish: bool
    slots: tuple[str, str, str]

    @field_validator("slots")
    @classmethod
    def valid_unique_times(cls, value: tuple[str, str, str]) -> tuple[str, str, str]:
        if len(set(value)) != 3:
            raise ValueError("publication_slots_must_be_unique")
        for slot in value:
            try:
                hour, minute = (int(part) for part in slot.split(":"))
            except (TypeError, ValueError):
                raise ValueError("invalid_publication_slot") from None
            if len(slot) != 5 or not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError("invalid_publication_slot")
        return value


class SourceScheduleRequest(RequestSchema):
    id: int = Field(gt=0)
    schedule: str = Field(min_length=1)

    @field_validator("schedule")
    @classmethod
    def valid_cron(cls, value: str) -> str:
        return normalize_cron(value)


class RouteScheduleRequest(PublicationScheduleRequest):
    id: int = Field(gt=0)


class ScheduleSettingsRequest(RequestSchema):
    sources: tuple[SourceScheduleRequest, ...]
    routes: tuple[RouteScheduleRequest, ...]

    @model_validator(mode="after")
    def unique_resource_ids(self):
        if len({item.id for item in self.sources}) != len(self.sources):
            raise ValueError("duplicate_source_schedule")
        if len({item.id for item in self.routes}) != len(self.routes):
            raise ValueError("duplicate_route_schedule")
        return self


class RouteRequest(RequestSchema):
    format_id: int = Field(gt=0)
    channel_id: int = Field(gt=0)
    cta_id: int | None = Field(default=None, gt=0)
    enabled: bool
    schedule: PublicationScheduleRequest | None = None


ResourceRequest = SourceRequest | ChannelRequest | CtaRequest | RouteRequest
