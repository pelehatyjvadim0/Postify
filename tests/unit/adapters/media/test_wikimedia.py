from __future__ import annotations

import httpx


def test_wikimedia_search_uses_one_api_request_and_returns_original_file_url() -> None:
    # Поломка (gate 8): fallback делает N запросов или берёт thumbnail без source metadata.
    from postify.adapters.media.wikimedia import WikimediaImageSearch

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": {
                        "42": {
                            "title": "File:PostgreSQL.png",
                            "imageinfo": [{"url": "https://upload.wikimedia.org/postgresql.png"}],
                        }
                    }
                }
            },
            request=request,
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
