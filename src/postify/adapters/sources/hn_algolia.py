from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx

from postify.application.ports.candidate_source import SourceFetchError
from postify.domain.candidates.models import Candidate, CandidateValidationError


class HnAlgoliaCandidateSource:
    def __init__(
        self,
        *,
        client: httpx.Client,
        url: str,
        query: str,
        tags: str,
        hits: int,
    ) -> None:
        self._client = client
        self._url = url
        self._query = query
        self._tags = tags
        self._hits = hits

    def fetch(self) -> Sequence[Candidate]:
        try:
            response = self._client.get(
                self._url,
                params={
                    "query": self._query,
                    "tags": self._tags,
                    "hitsPerPage": self._hits,
                },
            )
            response.raise_for_status()
            payload = response.json()
            hits = self._hits_from(payload)
        except (httpx.HTTPError, ValueError) as error:
            raise SourceFetchError("Не удалось получить кандидатов из источника") from error

        return [candidate for hit in hits if (candidate := self._candidate_from(hit)) is not None]

    @staticmethod
    def _hits_from(payload: Any) -> list[Any]:
        if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
            raise ValueError("source response must contain a hits list")
        return payload["hits"]

    @staticmethod
    def _candidate_from(hit: Any) -> Candidate | None:
        if not isinstance(hit, Mapping):
            return None

        source_id = HnAlgoliaCandidateSource._first_text(hit, "objectID")
        title = HnAlgoliaCandidateSource._first_text(hit, "title", "story_title")
        url = HnAlgoliaCandidateSource._first_text(hit, "url", "story_url")
        discovered_at = HnAlgoliaCandidateSource._discovered_at(hit.get("created_at_i"))
        if source_id is None or title is None or url is None or discovered_at is None:
            return None

        try:
            return Candidate(
                source_name="hacker_news",
                source_id=source_id,
                title=title,
                url=url,
                discovered_at=discovered_at,
                raw_payload=hit,
            )
        except CandidateValidationError:
            return None

    @staticmethod
    def _first_text(hit: Mapping[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = hit.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    @staticmethod
    def _discovered_at(value: Any) -> datetime | None:
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
