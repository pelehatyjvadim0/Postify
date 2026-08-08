from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import re

import httpx
import pytest


NOW = datetime(2026, 8, 8, 12, tzinfo=UTC)


class FakeWikimedia:
    def __init__(self, result: tuple[str, str] | None) -> None:
        self.result = result
        self.queries: list[str] = []

    def search(self, query: str) -> tuple[str, str] | None:
        self.queries.append(query)
        return self.result


def _api():
    from postify.adapters.media.local_media_provider import LocalMediaProvider, MediaAcquireError
    from postify.domain.content.models import ExtractedArticle

    return ExtractedArticle, LocalMediaProvider, MediaAcquireError


def _article(ExtractedArticle, candidates: tuple[tuple[str, str], ...]):
    return ExtractedArticle(
        source_url="https://source.test/post",
        title="Article",
        text="A complete extracted article body with enough meaningful detail.",
        image_candidates=candidates,
    )


def test_media_uses_first_valid_article_candidate_without_wikimedia(tmp_path: Path) -> None:
    # Поломка (gate 8): Wikimedia вызывается до доступного og/twitter/article.
    ExtractedArticle, LocalMediaProvider, _ = _api()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path.endswith("og.jpg"):
            return httpx.Response(404, request=request)
        return httpx.Response(
            200,
            content=b"valid-png-bytes",
            headers={"content-type": "image/png"},
            request=request,
        )

    wiki = FakeWikimedia(("wikimedia", "https://wiki.test/fallback.webp"))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = LocalMediaProvider(client, tmp_path, 1000, wiki)
        media = provider.acquire(
            _article(
                ExtractedArticle,
                (
                    ("og", "https://cdn.test/og.jpg"),
                    ("twitter", "https://cdn.test/twitter.png"),
                    ("article", "https://cdn.test/inline.webp"),
                ),
            ),
            "database",
        )

    assert requests == ["https://cdn.test/og.jpg", "https://cdn.test/twitter.png"]
    assert wiki.queries == []
    assert media.source_type == "twitter"
    assert media.source_url == "https://cdn.test/twitter.png"
    assert Path(media.local_path).read_bytes() == b"valid-png-bytes"


def test_media_falls_back_once_to_wikimedia_after_all_article_candidates(tmp_path: Path) -> None:
    # Поломка (gate 8): fallback перемешан с article-источниками или вызван не один раз.
    ExtractedArticle, LocalMediaProvider, _ = _api()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.host == "wiki.test":
            return httpx.Response(
                200,
                content=b"webp",
                headers={"content-type": "image/webp"},
                request=request,
            )
        return httpx.Response(404, request=request)

    wiki = FakeWikimedia(("wikimedia", "https://wiki.test/fallback.webp"))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        media = LocalMediaProvider(client, tmp_path, 1000, wiki).acquire(
            _article(ExtractedArticle, (("og", "https://cdn.test/og.jpg"),)),
            "database",
        )

    assert requests == ["https://cdn.test/og.jpg", "https://wiki.test/fallback.webp"]
    assert wiki.queries == ["database"]
    assert media.source_type == "wikimedia"


@pytest.mark.parametrize(
    ("body", "mime", "max_bytes"),
    [
        (b"", "image/png", 10),
        (b"x" * 11, "image/png", 10),
        (b"text", "text/html", 10),
        (b"gif", "image/gif", 10),
    ],
)
def test_media_rejects_empty_oversized_or_disallowed_mime(
    tmp_path: Path, body: bytes, mime: str, max_bytes: int
) -> None:
    # Поломка (gate 8/10): невалидный download записан как медиа.
    ExtractedArticle, LocalMediaProvider, MediaAcquireError = _api()
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=body, headers={"content-type": mime}, request=request
            )
        )
    ) as client:
        provider = LocalMediaProvider(client, tmp_path, max_bytes, FakeWikimedia(None))
        with pytest.raises(MediaAcquireError):
            provider.acquire(
                _article(ExtractedArticle, (("og", "https://cdn.test/image"),)),
                "database",
            )

    assert list(tmp_path.iterdir()) == []


def test_media_uses_uuid_mime_extension_containment_and_atomic_final_file(tmp_path: Path) -> None:
    # Поломка (gate 8): URL filename traversal/расширение становятся local path.
    ExtractedArticle, LocalMediaProvider, _ = _api()
    evil = "https://cdn.test/%2e%2e/%2e%2e/secret.exe?name=stolen.jpg"
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"jpeg",
                headers={"content-type": "image/jpeg"},
                request=request,
            )
        )
    ) as client:
        media = LocalMediaProvider(client, tmp_path, 100, FakeWikimedia(None)).acquire(
            _article(ExtractedArticle, (("og", evil),)), "database"
        )

    local_path = Path(media.local_path)
    assert local_path.parent == tmp_path.resolve()
    assert re.fullmatch(r"[0-9a-f]{32}\.jpg", local_path.name)
    assert local_path.read_bytes() == b"jpeg"
    assert [path for path in tmp_path.iterdir() if path.name != local_path.name] == []


def test_cleanup_removes_only_expired_unprotected_files(tmp_path: Path) -> None:
    # Поломка (gate 9): TTL удаляет активное/молодое медиа или не удаляет orphan.
    _, LocalMediaProvider, _ = _api()
    expired = tmp_path / "expired.jpg"
    protected = tmp_path / "protected.jpg"
    young = tmp_path / "young.jpg"
    for path in (expired, protected, young):
        path.write_bytes(b"x")
    old_timestamp = (NOW - timedelta(hours=49)).timestamp()
    new_timestamp = (NOW - timedelta(hours=47)).timestamp()
    import os

    os.utime(expired, (old_timestamp, old_timestamp))
    os.utime(protected, (old_timestamp, old_timestamp))
    os.utime(young, (new_timestamp, new_timestamp))
    with httpx.Client() as client:
        provider = LocalMediaProvider(client, tmp_path, 100, FakeWikimedia(None))
        removed = provider.cleanup(
            older_than=NOW - timedelta(hours=48),
            protected_paths={str(protected)},
        )

    assert removed == 1
    assert not expired.exists()
    assert protected.exists()
    assert young.exists()
