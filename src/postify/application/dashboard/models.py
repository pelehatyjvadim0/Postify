from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping


@dataclass(frozen=True, slots=True)
class DashboardOverview:
    candidate_total: int
    undecided_materials: int
    selected_materials: int
    package_total: int
    approved_packages: int
    published_today: int
    daily_analyses_started: int
    daily_packages_created: int


@dataclass(frozen=True, slots=True)
class Material:
    candidate_id: int
    source_name: str
    title: str
    url: str
    discovered_at: datetime
    decision_status: str | None
    decision_reason: str | None
    decision_explanation: str | None
    decision_signals: Mapping[str, object] | None
    policy_version: str | None


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


@dataclass(frozen=True, slots=True)
class PackageHistoryEntry:
    status: str
    reason: str
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


@dataclass(frozen=True, slots=True)
class QueueSlot:
    route_id: int
    provider: str
    slot_time: str
    assignment_kind: str
    package_id: int | None
    delivery_id: int | None


@dataclass(frozen=True, slots=True)
class PublicationAttempt:
    attempt_no: int
    outcome: str
    code: str | None
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
