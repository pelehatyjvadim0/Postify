from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Material:
    candidate_id: int
    source_name: str
    title: str
    url: str
    discovered_at: datetime
    retry_attempt_id: int | None = None
    generation_status: str | None = None
    generation_failure_code: str | None = None
    original_text: str | None = None


@dataclass(frozen=True, slots=True)
class PackageSummary:
    package_id: int
    status: str
    source_url: str
    post_text: str
    media_available: bool
    media_status: str
    created_at: datetime
    updated_at: datetime


    scheduled_at: datetime | None = None
    route_id: int | None = None
    candidate_id: int | None = None
    previous_package_id: int | None = None


@dataclass(frozen=True, slots=True)
class PackageHistoryEntry:
    status: str
    reason: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PackageDetail:
    package_id: int
    status: str
    source_url: str
    post_text: str
    analysis: str
    media_available: bool
    media_status: str
    media_source_type: str | None
    media_source_url: str | None
    history: tuple[PackageHistoryEntry, ...]
    generation_snapshot: Mapping[str, object]
    created_at: datetime
    updated_at: datetime
    attempt_id: int | None = None
    original_text: str = ""
    scheduled_at: datetime | None = None
    route_id: int | None = None
    delivery_status: str | None = None
    replacement_package_id: int | None = None


@dataclass(frozen=True, slots=True)
class QueueSlot:
    route_id: int
    provider: str
    slot_time: str
    assignment_kind: str
    package_id: int | None
    delivery_id: int | None


    scheduled_at: datetime | None = None
    status: str | None = None
    delivery_status: str | None = None
    channel_name: str | None = None
    post_text: str = ""
    failure_code: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PublicationAttempt:
    attempt_no: int
    outcome: str
    code: str | None
    reason: str | None
    message_id: int | None
    started_at: datetime
    finished_at: datetime


@dataclass(frozen=True, slots=True)
class Publication:
    delivery_id: int
    package_id: int
    provider: str | None
    status: str
    attempt_count: int
    attempts: tuple[PublicationAttempt, ...]
    message_id: int | None
    failure_code: str | None
    failure_reason: str | None
    sending_started_at: datetime
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Operation:
    run_id: int
    kind: str
    status: str
    outcome: str | None
    failure_code: str | None
    started_at: datetime
    finished_at: datetime | None
    duration: timedelta | None
    mode: str = "automatic"
    actor: str = "scheduler"
    codex_model: str | None = None
    codex_reasoning_effort: str | None = None
    materials_taken: int = 0
    packages_created: int = 0
