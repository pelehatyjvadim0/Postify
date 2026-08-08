from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
from urllib.parse import urlsplit

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


class AllowingPolicy:
    """Тестовый safe fake: разрешает только структурно безопасные HTTP(S) URL."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def validate(self, url: str) -> str:
        self.urls.append(url)
        parsed = urlsplit(url)
        assert parsed.scheme in {"http", "https"}
        assert parsed.hostname
        assert parsed.username is None and parsed.password is None
        assert parsed.port is None or 1 <= parsed.port <= 65535
        return url


class RecordingStream(httpx.SyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...], *, fail_after: int | None = None) -> None:
        self.chunks = chunks
        self.fail_after = fail_after
        self.reads = 0

    def __iter__(self):
        for chunk in self.chunks:
            self.reads += 1
            if self.fail_after is not None and self.reads > self.fail_after:
                raise AssertionError("body прочитан после доказанного превышения лимита")
            yield chunk


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
        provider = LocalMediaProvider(
            client, tmp_path, 1000, wiki, url_policy=AllowingPolicy()
        )
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
        media = LocalMediaProvider(
            client, tmp_path, 1000, wiki, url_policy=AllowingPolicy()
        ).acquire(
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
        provider = LocalMediaProvider(
            client,
            tmp_path,
            max_bytes,
            FakeWikimedia(None),
            url_policy=AllowingPolicy(),
        )
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
        media = LocalMediaProvider(
            client,
            tmp_path,
            100,
            FakeWikimedia(None),
            url_policy=AllowingPolicy(),
        ).acquire(
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
        provider = LocalMediaProvider(
            client,
            tmp_path,
            100,
            FakeWikimedia(None),
            url_policy=AllowingPolicy(),
        )
        removed = provider.cleanup(
            older_than=NOW - timedelta(hours=48),
            protected_paths={str(protected)},
        )

    assert removed == 1
    assert not expired.exists()
    assert protected.exists()
    assert young.exists()


@pytest.mark.parametrize(
    "policy_kwargs",
    [{}, {"url_policy": None}],
    ids=["omitted", "none"],
)
def test_media_provider_cannot_be_constructed_without_public_url_policy(
    tmp_path: Path,
    policy_kwargs: dict[str, object],
) -> None:
    # Поломка fix-round 1: optional/None policy оставляет media SSRF bypass.
    _, LocalMediaProvider, _ = _api()

    with httpx.Client(transport=httpx.MockTransport(lambda request: None)) as client:
        with pytest.raises(TypeError):
            LocalMediaProvider(
                client,
                tmp_path,
                100,
                FakeWikimedia(None),
                **policy_kwargs,
            )


def test_media_rejects_unsafe_url_before_opening_http_stream(tmp_path: Path) -> None:
    # Поломка re-review 1: media adapter вызывает HTTP до общей URL policy.
    ExtractedArticle, LocalMediaProvider, MediaAcquireError = _api()
    from postify.adapters.http.public_url_policy import UnsafePublicUrlError

    requests: list[httpx.Request] = []

    class RejectingPolicy:
        def validate(self, url: str) -> str:
            raise UnsafePublicUrlError("unsafe_url")

    def forbidden(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("небезопасный URL не должен достигать HTTP")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        provider = LocalMediaProvider(
            client,
            tmp_path,
            100,
            FakeWikimedia(None),
            url_policy=RejectingPolicy(),
        )
        with pytest.raises(MediaAcquireError) as caught:
            provider.acquire(
                _article(
                    ExtractedArticle,
                    (("og", "http://169.254.169.254/meta-data"),),
                ),
                "database",
            )

    assert requests == []
    assert caught.value.code == "media_failed"
    assert "169.254" not in str(caught.value)


def test_media_does_not_follow_redirect_or_load_redirect_target(tmp_path: Path) -> None:
    # Поломка re-review 1: redirect обходит проверку URL media candidate.
    ExtractedArticle, LocalMediaProvider, MediaAcquireError = _api()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if len(requests) == 1:
            return httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/private.png"},
                request=request,
            )
        return httpx.Response(
            200,
            content=b"private-image",
            headers={"content-type": "image/png"},
            request=request,
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        provider = LocalMediaProvider(
            client,
            tmp_path,
            100,
            FakeWikimedia(None),
            url_policy=AllowingPolicy(),
        )
        with pytest.raises(MediaAcquireError):
            provider.acquire(
                _article(
                    ExtractedArticle,
                    (("og", "https://public.test/image.png"),),
                ),
                "database",
            )

    assert requests == ["https://public.test/image.png"]
    assert list(tmp_path.iterdir()) == []


def test_media_content_length_over_limit_is_rejected_before_body_read(
    tmp_path: Path,
) -> None:
    # Поломка re-review 2: oversized media Content-Length читается в память.
    ExtractedArticle, LocalMediaProvider, MediaAcquireError = _api()
    stream = RecordingStream((b"must-not-be-read",), fail_after=0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "image/png", "content-length": "101"},
            stream=stream,
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = LocalMediaProvider(
            client,
            tmp_path,
            100,
            FakeWikimedia(None),
            url_policy=AllowingPolicy(),
        )
        with pytest.raises(MediaAcquireError) as caught:
            provider.acquire(
                _article(
                    ExtractedArticle,
                    (("og", "https://public.test/image.png"),),
                ),
                "database",
            )

    assert stream.reads == 0
    assert caught.value.code == "media_failed"
    assert list(tmp_path.iterdir()) == []


def test_media_chunk_overflow_stops_without_reading_remaining_body(
    tmp_path: Path,
) -> None:
    # Поломка re-review 2: media overflow дочитывает/materialize response.content.
    ExtractedArticle, LocalMediaProvider, MediaAcquireError = _api()
    stream = RecordingStream((b"a" * 60, b"b" * 60, b"secret-tail"), fail_after=2)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            stream=stream,
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = LocalMediaProvider(
            client,
            tmp_path,
            100,
            FakeWikimedia(None),
            url_policy=AllowingPolicy(),
        )
        with pytest.raises(MediaAcquireError):
            provider.acquire(
                _article(
                    ExtractedArticle,
                    (("og", "https://public.test/image.png"),),
                ),
                "database",
            )

    assert stream.reads == 2
    assert list(tmp_path.iterdir()) == []


def test_delete_rejects_path_outside_media_root(tmp_path: Path) -> None:
    # Поломка re-review 10: reject может удалить произвольный абсолютный путь.
    _, LocalMediaProvider, MediaAcquireError = _api()
    media_root = tmp_path / "media"
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    with httpx.Client() as client:
        provider = LocalMediaProvider(
            client,
            media_root,
            100,
            FakeWikimedia(None),
            url_policy=AllowingPolicy(),
        )
        with pytest.raises(MediaAcquireError):
            provider.delete(str(outside))

    assert outside.read_text(encoding="utf-8") == "keep"


def test_delete_rejects_symlink_even_when_link_is_inside_media_root(tmp_path: Path) -> None:
    # Поломка re-review 10: symlink внутри root удаляет/затрагивает внешний target.
    _, LocalMediaProvider, MediaAcquireError = _api()
    media_root = tmp_path / "media"
    media_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    link = media_root / "linked.jpg"
    link.symlink_to(outside)
    with httpx.Client() as client:
        provider = LocalMediaProvider(
            client,
            media_root,
            100,
            FakeWikimedia(None),
            url_policy=AllowingPolicy(),
        )
        with pytest.raises(MediaAcquireError):
            provider.delete(str(link))

    assert link.is_symlink()
    assert outside.read_text(encoding="utf-8") == "keep"


def test_delete_rejects_intermediate_symlink_even_when_target_stays_inside_root(
    tmp_path: Path,
) -> None:
    # Поломка fix-round 1: resolve-only containment разрешает symlink в родителе.
    _, LocalMediaProvider, MediaAcquireError = _api()
    media_root = tmp_path / "media"
    real_directory = media_root / "real"
    real_directory.mkdir(parents=True)
    stored = real_directory / "stored.jpg"
    stored.write_bytes(b"keep")
    linked_directory = media_root / "linked"
    linked_directory.symlink_to(real_directory, target_is_directory=True)

    with httpx.Client() as client:
        provider = LocalMediaProvider(
            client,
            media_root,
            100,
            FakeWikimedia(None),
            url_policy=AllowingPolicy(),
        )
        with pytest.raises(MediaAcquireError) as caught:
            provider.delete(str(linked_directory / "stored.jpg"))

    assert caught.value.code == "media_failed"
    assert linked_directory.is_symlink()
    assert stored.read_bytes() == b"keep"


def test_cleanup_normalizes_filesystem_error_without_leaking_absolute_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Поломка fix-round 1: cleanup выпускает raw OSError с путём.
    _, LocalMediaProvider, MediaAcquireError = _api()
    expired = tmp_path / "operator-secret" / "expired.jpg"
    expired.parent.mkdir()
    expired.write_bytes(b"recoverable")
    old_timestamp = (NOW - timedelta(hours=49)).timestamp()
    import os

    os.utime(expired, (old_timestamp, old_timestamp))
    original_unlink = Path.unlink

    def failing_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == expired:
            raise OSError(f"filesystem failure at {expired}")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with httpx.Client() as client:
        provider = LocalMediaProvider(
            client,
            expired.parent,
            100,
            FakeWikimedia(None),
            url_policy=AllowingPolicy(),
        )
        with pytest.raises(MediaAcquireError) as caught:
            provider.cleanup(
                older_than=NOW - timedelta(hours=48),
                protected_paths=set(),
            )

    assert caught.value.code == "media_failed"
    assert str(expired) not in str(caught.value)
    assert "operator-secret" not in str(caught.value)
    assert expired.read_bytes() == b"recoverable"


def test_media_provider_owns_og_twitter_article_priority_for_unsorted_input(
    tmp_path: Path,
) -> None:
    # Поломка fix-round 1: provider доверяет порядку входа и берёт article до og.
    ExtractedArticle, LocalMediaProvider, _ = _api()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            200,
            content=b"selected-og",
            headers={"content-type": "image/jpeg"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        media = LocalMediaProvider(
            client,
            tmp_path,
            100,
            FakeWikimedia(None),
            url_policy=AllowingPolicy(),
        ).acquire(
            _article(
                ExtractedArticle,
                (
                    ("article", "https://cdn.test/article.jpg"),
                    ("twitter", "https://cdn.test/twitter.jpg"),
                    ("og", "https://cdn.test/og.jpg"),
                ),
            ),
            "database",
        )

    assert requests == ["https://cdn.test/og.jpg"]
    assert media.source_type == "og"
    assert media.source_url == "https://cdn.test/og.jpg"
    assert Path(media.local_path).read_bytes() == b"selected-og"
