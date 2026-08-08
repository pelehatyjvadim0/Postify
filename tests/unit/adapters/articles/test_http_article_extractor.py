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
        result = HttpArticleExtractor(client=client, max_bytes=10_000, min_text_chars=40).extract(
            "https://source.test/path/post"
        )

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
            article = HttpArticleExtractor(client=client, max_bytes=10_000, min_text_chars=30).extract(
                "https://source.test/post"
            )
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
        extractor = HttpArticleExtractor(client=client, max_bytes=max_bytes, min_text_chars=30)
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
        article = HttpArticleExtractor(client=client, max_bytes=10_000, min_text_chars=30).extract(
            "https://source.test/news/post"
        )

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
            HttpArticleExtractor(client=client, max_bytes=1000, min_text_chars=30).extract(
                secret_url
            )

    assert caught.value.code == "article_unavailable"
    assert "secret" not in str(caught.value)
    assert "private.test" not in str(caught.value)
