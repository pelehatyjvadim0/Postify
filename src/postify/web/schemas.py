from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from postify.domain.projects.cron import normalize_cron


class RequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RejectRequest(RequestSchema):
    reason: str = Field(min_length=3, max_length=500)


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
