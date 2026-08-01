from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from postify.domain.candidates.models import Candidate, CandidateValidationError


def valid_candidate_data(**overrides: object) -> dict[str, object]:
    return {
        "source_name": "hacker_news",
        "source_id": "123",
        "title": "A useful post",
        "url": "https://example.test/posts/123",
        "discovered_at": datetime(2026, 8, 1, 9, 30, tzinfo=UTC),
        "raw_payload": {"objectID": "123", "tags": ["story", "python"]},
        **overrides,
    }


@pytest.mark.parametrize("field", ["source_name", "source_id", "title", "url"])
@pytest.mark.parametrize("value", ["", "   \t\n"])
def test_candidate_rejects_blank_required_text_field(field: str, value: str) -> None:
    with pytest.raises(CandidateValidationError, match=field):
        Candidate(**valid_candidate_data(**{field: value}))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "url",
    [
        "/posts/123",
        "posts/123",
        "ftp://example.test/posts/123",
        "https:///posts/123",
    ],
)
def test_candidate_rejects_url_without_absolute_http_host(url: str) -> None:
    with pytest.raises(CandidateValidationError, match="url"):
        Candidate(**valid_candidate_data(url=url))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/posts/123",
        "https://example.test:8443/posts/123?sort=new",
    ],
)
def test_candidate_accepts_absolute_http_url_with_host(url: str) -> None:
    candidate = Candidate(**valid_candidate_data(url=url))  # type: ignore[arg-type]

    assert candidate.url == url


def test_candidate_rejects_naive_discovery_time() -> None:
    with pytest.raises(CandidateValidationError, match="discovered_at"):
        Candidate(**valid_candidate_data(discovered_at=datetime(2026, 8, 1, 9, 30)))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "discovered_at",
    [
        datetime(2026, 8, 1, 9, 30, tzinfo=UTC),
        datetime(2026, 8, 1, 12, 30, tzinfo=timezone(timedelta(hours=3))),
    ],
)
def test_candidate_accepts_aware_discovery_time(discovered_at: datetime) -> None:
    candidate = Candidate(**valid_candidate_data(discovered_at=discovered_at))  # type: ignore[arg-type]

    assert candidate.discovered_at == discovered_at


def test_candidate_keeps_deep_copy_of_raw_payload() -> None:
    payload = {"objectID": "123", "meta": {"score": 42}, "tags": ["story"]}

    candidate = Candidate(**valid_candidate_data(raw_payload=payload))  # type: ignore[arg-type]
    payload["meta"]["score"] = 99  # type: ignore[index]
    payload["tags"].append("python")  # type: ignore[index]

    assert candidate.raw_payload == {
        "objectID": "123",
        "meta": {"score": 42},
        "tags": ["story"],
    }
