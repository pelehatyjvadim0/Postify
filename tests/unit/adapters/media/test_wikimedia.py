from __future__ import annotations

import httpx


def _file_page(url: str, mime: str) -> dict[str, object]:
    return {
        "title": "File:fixture",
        "imageinfo": [{"url": url, "mime": mime}],
    }


def _commons_response(
    request: httpx.Request, pages: dict[str, object]
) -> httpx.Response:
    return httpx.Response(200, json={"query": {"pages": pages}}, request=request)


def test_wikimedia_search_uses_one_api_request_and_returns_original_file_url() -> None:
    # Поломка (gate 8): fallback делает N запросов или берёт thumbnail без source metadata.
    from postify.adapters.media.wikimedia import WikimediaImageSearch

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _commons_response(
            request,
            {
                "42": _file_page(
                    "https://upload.wikimedia.org/postgresql.png", "image/png"
                )
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = WikimediaImageSearch(client=client).search("PostgreSQL database")

    assert result == (
        "wikimedia",
        "https://upload.wikimedia.org/postgresql.png",
    )
    assert len(requests) == 1
    assert requests[0].url.params["generator"] == "search"
    assert (
        requests[0].headers["user-agent"],
        requests[0].url.params.get("gsrnamespace"),
    ) == ("Postify/0.1", "6")


def test_wikimedia_search_returns_none_for_http_and_json_errors() -> None:
    # Поломка live fix: Commons failure выходит наружу вместо safe None.
    from postify.adapters.media.wikimedia import WikimediaImageSearch

    def http_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Commons unavailable", request=request)

    def json_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", request=request)

    for handler in (http_error, json_error):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            assert WikimediaImageSearch(client=client).search("PostgreSQL") is None


def test_wikimedia_search_skips_unsupported_files_and_requests_mime() -> None:
    # Поломка live round 2: первый PDF/SVG попадает в media download.
    from postify.adapters.media.wikimedia import WikimediaImageSearch

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _commons_response(
            request,
            {
                "pdf": _file_page(
                    "https://upload.wikimedia.org/manual.pdf", "application/pdf"
                ),
                "svg": _file_page(
                    "https://upload.wikimedia.org/logo.svg", "image/svg+xml"
                ),
                "png": _file_page(
                    "https://upload.wikimedia.org/diagram.png", "image/png"
                ),
                "jpeg": _file_page(
                    "https://upload.wikimedia.org/photo.jpg", "image/jpeg"
                ),
                "webp": _file_page(
                    "https://upload.wikimedia.org/preview.webp", "image/webp"
                ),
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = WikimediaImageSearch(client=client).search("PostgreSQL database")

    assert (
        result,
        len(requests),
        set(requests[0].url.params["iiprop"].split("|")),
    ) == (
        ("wikimedia", "https://upload.wikimedia.org/diagram.png"),
        1,
        {"url", "mime"},
    )


def test_wikimedia_search_returns_none_when_no_valid_supported_file_exists() -> None:
    # Поломка live round 2: unsupported/malformed entry принимается как image.
    from postify.adapters.media.wikimedia import WikimediaImageSearch

    def handler(request: httpx.Request) -> httpx.Response:
        return _commons_response(
            request,
            {
                "pdf": _file_page(
                    "https://upload.wikimedia.org/manual.pdf", "application/pdf"
                ),
                "svg": _file_page(
                    "https://upload.wikimedia.org/logo.svg", "image/svg+xml"
                ),
                "missing-imageinfo": {},
                "empty-imageinfo": {"imageinfo": []},
                "missing-url": {"imageinfo": [{"mime": "image/png"}]},
                "invalid-entry": {"imageinfo": [None]},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = WikimediaImageSearch(client=client).search("PostgreSQL database")

    assert result is None
