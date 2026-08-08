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
