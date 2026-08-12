from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


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
    selection_policy_version: str | None = Field(default=None, min_length=1)
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


class RouteRequest(RequestSchema):
    format_id: int = Field(gt=0)
    channel_id: int = Field(gt=0)
    cta_id: int | None = Field(default=None, gt=0)
    enabled: bool


ResourceRequest = SourceRequest | ChannelRequest | CtaRequest | RouteRequest
