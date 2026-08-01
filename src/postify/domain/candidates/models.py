from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlsplit


class CandidateValidationError(ValueError):
    """Сообщает о нарушении инварианта кандидата."""


@dataclass(frozen=True, slots=True)
class Candidate:
    source_name: str
    source_id: str
    title: str
    url: str
    discovered_at: datetime
    raw_payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        self._validate_required_text_fields()
        self._validate_url()
        self._validate_discovered_at()
        object.__setattr__(self, "raw_payload", deepcopy(dict(self.raw_payload)))

    def _validate_required_text_fields(self) -> None:
        for field_name in ("source_name", "source_id", "title", "url"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise CandidateValidationError(f"{field_name} must not be blank")

    def _validate_url(self) -> None:
        parsed_url = urlsplit(self.url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            raise CandidateValidationError("url must be an absolute http or https URL with a host")

    def _validate_discovered_at(self) -> None:
        if self.discovered_at.tzinfo is None or self.discovered_at.utcoffset() is None:
            raise CandidateValidationError("discovered_at must be timezone-aware")
