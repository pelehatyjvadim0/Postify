from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from postify.adapters.sources.hn_algolia import HnAlgoliaCandidateSource
from postify.application.ports.candidate_source import SourceFetchError


def realistic_hit(**overrides: Any) -> dict[str, Any]:
    return {
        "_highlightResult": {
            "title": {"value": "<em>Postify</em> launch", "matchLevel": "full"},
            "url": {"value": "https://example.test/postify", "matchLevel": "none"},
        },
        "_tags": ["story", "author_alice", "story_12345"],
        "author": "alice",
        "children": [],
        "created_at": "2026-08-01T09:30:00.000Z",
        "created_at_i": 1785576600,
        "num_comments": 42,
        "objectID": "12345",
        "points": 128,
        "story_id": 12345,
        "story_title": "Postify launch",
        "story_url": "https://example.test/postify",
        "title": "Postify launch",
        "url": "https://example.test/postify",
        **overrides,
    }


@pytest.mark.parametrize(
    ("query", "tags"),
    [
        ("OpenAI API", "story"),
        ("local-first developer tools", "story,front_page"),
    ],
)
def test_fetch_sends_explicit_query_profile(query: str, tags: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"hits": [realistic_hit()]})

    source = HnAlgoliaCandidateSource(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        url="https://hn.algolia.test/api/v1/search",
        query=query,
        tags=tags,
        hits=25,
    )

    candidates = source.fetch()

    assert len(candidates) == 1
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert dict(requests[0].url.params) == {
        "query": query,
        "tags": tags,
        "hitsPerPage": "25",
    }


def test_fetch_maps_valid_hits_with_fallback_fields_utc_time_and_raw_payload() -> None:
    hit = realistic_hit(title="", story_title="Fallback title", url="", story_url="https://example.test/fallback")
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"hits": [hit]}))
    )
    source = HnAlgoliaCandidateSource(
        client=client,
        url="https://hn.algolia.test/api/v1/search",
        query="database migrations",
        tags="story",
        hits=10,
    )

    candidates = source.fetch()

    assert len(candidates) == 1
    assert candidates[0].source_name == "hacker_news"
    assert candidates[0].source_id == "12345"
    assert candidates[0].title == "Fallback title"
    assert candidates[0].url == "https://example.test/fallback"
    assert candidates[0].discovered_at == datetime.fromtimestamp(1785576600, tz=UTC)
    assert candidates[0].discovered_at.tzinfo is UTC
    assert candidates[0].raw_payload == hit


def test_fetch_skips_invalid_hits_without_losing_valid_ones() -> None:
    valid = realistic_hit(objectID="valid")
    invalid = realistic_hit(objectID="", title="", story_title="", url="not a URL")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"hits": [invalid, valid]})
        )
    )
    source = HnAlgoliaCandidateSource(
        client=client,
        url="https://hn.algolia.test/api/v1/search",
        query="community tooling",
        tags="story",
        hits=10,
    )

    candidates = source.fetch()

    assert [candidate.source_id for candidate in candidates] == ["valid"]


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=request)),
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline", request=request)),
        lambda request: httpx.Response(429, request=request),
        lambda request: httpx.Response(503, request=request),
        lambda request: httpx.Response(200, text="not json", request=request),
        lambda request: httpx.Response(200, json={"nbHits": 1}, request=request),
    ],
)
def test_fetch_wraps_transport_and_invalid_response_failures(handler: Any) -> None:
    source = HnAlgoliaCandidateSource(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        url="https://hn.algolia.test/api/v1/search",
        query="security testing",
        tags="story",
        hits=10,
    )

    with pytest.raises(SourceFetchError) as error:
        source.fetch()

    assert error.value.__cause__ is not None
    assert "security testing" not in str(error.value)
    assert "not json" not in str(error.value)

