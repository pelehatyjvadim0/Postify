from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import TypeAlias


JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class DecisionStatus(StrEnum):
    SELECTED = "selected"
    REJECTED = "rejected"


class DecisionReason(StrEnum):
    ELIGIBLE_FOR_AI = "eligible_for_ai"
    ADVERTISING = "advertising"
    OUT_OF_SCOPE = "out_of_scope"
    HIRING = "hiring"
    TECHNICAL_WITHOUT_USE = "technical_without_use"


class RejectionRule(StrEnum):
    ADVERTISING = "advertising"
    OUT_OF_SCOPE = "out_of_scope"
    HIRING = "hiring"
    TECHNICAL_WITHOUT_USE = "technical_without_use"


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json(item) for item in value)
    return deepcopy(value)


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    candidate_id: int
    status: DecisionStatus
    reason: DecisionReason
    explanation: str
    signals: Mapping[str, JsonValue]
    policy_version: str
    decided_at: datetime

    def __post_init__(self) -> None:
        if self.candidate_id <= 0:
            raise ValueError("candidate_id must be positive")
        if not self.explanation.strip() or not self.policy_version.strip():
            raise ValueError("explanation and policy_version must not be blank")
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() is None:
            raise ValueError("decided_at must be timezone-aware")
        if (self.status is DecisionStatus.SELECTED) != (
            self.reason is DecisionReason.ELIGIBLE_FOR_AI
        ):
            raise ValueError("status and reason must be consistent")
        object.__setattr__(self, "signals", _freeze_json(self.signals))
