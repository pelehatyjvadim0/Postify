from __future__ import annotations

import httpx
import pytest


def _extractor_api():
    from postify.adapters.articles.http_article_extractor import (
        ArticleExtractionError,
        HttpArticleExtractor,
    )

    return ArticleExtractionError, HttpArticleExtractor


def _client(body: bytes, content_type: str = "text/html; charset=utf-8") -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=body,
                headers={"content-type": content_type},
                request=request,
            )
        )
    )


class AllowingPolicy:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def validate(self, url: str) -> str:
        self.urls.append(url)
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


def test_extract_prefers_article_text_and_discards_page_chrome() -> None:
    # Поломка (gate 4): AI получает nav/script или HN snippet вместо article body.
    _, HttpArticleExtractor = _extractor_api()
    marker = "ARTICLE-BODY-MARKER-92f4"
    html = f"""
        <html><head><title>Заголовок</title><script>SECRET_SCRIPT</script></head>
        <body><nav>MENU_NOISE</nav><main>Ложный main</main>
        <article><p>{marker} Первый содержательный абзац.</p>
        <p>Второй абзац с практическими деталями для читателя.</p></article></body></html>
    """.encode()
    with _client(html) as client:
        result = HttpArticleExtractor(
            client=client,
            max_bytes=10_000,
            min_text_chars=40,
        ).extract("https://source.test/path/post")

    assert marker in result.text
    assert "Второй абзац" in result.text
    assert "MENU_NOISE" not in result.text
    assert "SECRET_SCRIPT" not in result.text


def test_extract_uses_main_then_meaningful_paragraph_fallback() -> None:
    # Поломка: адаптер требует article и теряет доступный main/fallback.
    _, HttpArticleExtractor = _extractor_api()
    cases = (
        b"<main><p>MAIN-MARKER complete useful paragraph with enough details for extraction.</p></main>",
        b"<div><p>FALLBACK-MARKER complete useful paragraph with enough details for extraction.</p></div>",
    )

    markers: list[str] = []
    for html in cases:
        with _client(html) as client:
            article = HttpArticleExtractor(
                client=client,
                max_bytes=10_000,
                min_text_chars=30,
            ).extract("https://source.test/post")
        markers.append(article.text.split("-")[0])

    assert markers == ["MAIN", "FALLBACK"]


@pytest.mark.parametrize(
    ("body", "content_type", "max_bytes"),
    [
        (b"<article>short</article>", "text/html", 1000),
        (b"x" * 101, "text/html", 100),
        (b"{\"body\": \"not html\"}", "application/json", 1000),
    ],
)
def test_extract_rejects_short_oversized_or_non_html_response(
    body: bytes, content_type: str, max_bytes: int
) -> None:
    # Поломка (gate 10): невалидный HTTP-ответ попадает в Codex.
    ArticleExtractionError, HttpArticleExtractor = _extractor_api()
    with _client(body, content_type) as client:
        extractor = HttpArticleExtractor(
            client=client,
            max_bytes=max_bytes,
            min_text_chars=30,
        )
        with pytest.raises(ArticleExtractionError):
            extractor.extract("https://source.test/post")


def test_extract_preserves_strict_image_order_and_absolutizes_urls() -> None:
    # Поломка (gate 8): twitter/img обходят og или relative URL не абсолютизируется.
    _, HttpArticleExtractor = _extractor_api()
    html = b"""
      <html><head>
        <meta property="og:image" content="/images/og.jpg">
        <meta name="twitter:image" content="https://cdn.test/twitter.png">
      </head><body><article>
        <p>A complete useful article paragraph long enough to pass validation.</p>
        <img src="../inline.webp"><img src="data:image/png;base64,AAA">
      </article></body></html>
    """
    with _client(html) as client:
        article = HttpArticleExtractor(
            client=client,
            max_bytes=10_000,
            min_text_chars=30,
        ).extract("https://source.test/news/post")

    assert article.image_candidates == (
        ("og", "https://source.test/images/og.jpg"),
        ("twitter", "https://cdn.test/twitter.png"),
        ("article", "https://source.test/inline.webp"),
    )


def test_extract_normalizes_transport_error_without_leaking_source_url() -> None:
    # Поломка (gate 10): network exception сохраняет private URL/детали клиента.
    ArticleExtractionError, HttpArticleExtractor = _extractor_api()
    secret_url = "https://user:secret@private.test/article"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed {secret_url}", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ArticleExtractionError) as caught:
            HttpArticleExtractor(
                client=client,
                max_bytes=1000,
                min_text_chars=30,
            ).extract(secret_url)

    assert caught.value.code == "article_unavailable"
    assert "secret" not in str(caught.value)
    assert "private.test" not in str(caught.value)


def test_article_rejects_unsafe_url_before_opening_http_stream() -> None:
    # Поломка re-review 1: article adapter вызывает HTTP до общей URL policy.
    ArticleExtractionError, HttpArticleExtractor = _extractor_api()
    from postify.adapters.http.public_url_policy import UnsafePublicUrlError

    requests: list[httpx.Request] = []

    class RejectingPolicy:
        def validate(self, url: str) -> str:
            raise UnsafePublicUrlError("unsafe_url")

    def forbidden(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("небезопасный URL не должен достигать HTTP")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        with pytest.raises(ArticleExtractionError) as caught:
            HttpArticleExtractor(
                client=client,
                max_bytes=100,
                min_text_chars=30,
                url_policy=RejectingPolicy(),
            ).extract("http://127.0.0.1/admin")

    assert requests == []
    assert caught.value.code == "article_unavailable"
    assert "127.0.0.1" not in str(caught.value)


def test_article_does_not_follow_redirect_or_load_redirect_target() -> None:
    # Поломка re-review 1: client follow_redirects=True обходит policy через Location.
    ArticleExtractionError, HttpArticleExtractor = _extractor_api()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if len(requests) == 1:
            return httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/private"},
                request=request,
            )
        return httpx.Response(
            200,
            content=b"<article>private material that must never be loaded</article>",
            headers={"content-type": "text/html"},
            request=request,
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        with pytest.raises(ArticleExtractionError):
            HttpArticleExtractor(
                client=client,
                max_bytes=1000,
                min_text_chars=20,
                url_policy=AllowingPolicy(),
            ).extract("https://public.test/article")

    assert requests == ["https://public.test/article"]


def test_article_content_length_over_limit_is_rejected_before_body_read() -> None:
    # Поломка re-review 2: oversized Content-Length материализуется до проверки.
    ArticleExtractionError, HttpArticleExtractor = _extractor_api()
    stream = RecordingStream((b"must-not-be-read",), fail_after=0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-length": "101"},
            stream=stream,
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ArticleExtractionError) as caught:
            HttpArticleExtractor(
                client=client,
                max_bytes=100,
                min_text_chars=20,
                url_policy=AllowingPolicy(),
            ).extract("https://public.test/article")

    assert stream.reads == 0
    assert caught.value.code == "article_unavailable"


def test_article_chunk_overflow_stops_without_reading_remaining_body() -> None:
    # Поломка re-review 2: chunk overflow дочитывает/materialize весь response.
    ArticleExtractionError, HttpArticleExtractor = _extractor_api()
    stream = RecordingStream((b"a" * 60, b"b" * 60, b"secret-tail"), fail_after=2)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            stream=stream,
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ArticleExtractionError) as caught:
            HttpArticleExtractor(
                client=client,
                max_bytes=100,
                min_text_chars=20,
                url_policy=AllowingPolicy(),
            ).extract("https://public.test/article")

    assert stream.reads == 2
    assert caught.value.code == "article_unavailable"


def test_article_text_strictly_prefers_article_then_main_then_fallback() -> None:
    # Поломка re-review 11: parser смешивает article/main/общие p вместо приоритета.
    _, HttpArticleExtractor = _extractor_api()
    html = b"""
      <p>FALLBACK-NOISE paragraph long enough to be considered meaningful.</p>
      <main><p>MAIN-NOISE paragraph long enough to be considered meaningful.</p></main>
      <article><p>ARTICLE-WINNER paragraph long enough for extraction.</p></article>
    """
    with _client(html) as client:
        article = HttpArticleExtractor(
            client=client,
            max_bytes=10_000,
            min_text_chars=30,
            url_policy=AllowingPolicy(),
        ).extract("https://public.test/article")

    assert "ARTICLE-WINNER" in article.text
    assert "MAIN-NOISE" not in article.text
    assert "FALLBACK-NOISE" not in article.text


def test_image_metadata_priority_is_independent_of_document_order() -> None:
    # Поломка re-review 11: reversed meta order выдаёт twitter раньше og.
    _, HttpArticleExtractor = _extractor_api()
    html = b"""
      <head>
        <meta name="twitter:image" content="/twitter.png">
        <meta property="og:image" content="/og.jpg">
      </head>
      <article><p>Useful article text long enough.</p><img src="/inline.webp"></article>
    """
    with _client(html) as client:
        article = HttpArticleExtractor(
            client=client,
            max_bytes=10_000,
            min_text_chars=20,
            url_policy=AllowingPolicy(),
        ).extract("https://public.test/article")

    assert article.image_candidates == (
        ("og", "https://public.test/og.jpg"),
        ("twitter", "https://public.test/twitter.png"),
        ("article", "https://public.test/inline.webp"),
    )
