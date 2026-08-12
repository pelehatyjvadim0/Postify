import pytest

from postify.adapters.channels.registry import ChannelProviderRegistry
from postify.adapters.sources.registry import SourceProviderRegistry
from postify.domain.projects.models import UnsupportedProvider


def test_source_registry_normalises_hn_algolia_configuration() -> None:
    result = SourceProviderRegistry().validate(
        "hn_algolia",
        {
            "url": "https://hn.algolia.com/api/v1/search_by_date",
            "query": "  python agents ",
            "tags": " story ",
            "hits": 50,
        },
    )

    assert result == {
        "url": "https://hn.algolia.com/api/v1/search_by_date",
        "query": "python agents",
        "tags": "story",
        "hits": 50,
    }


def test_source_registry_rejects_unknown_provider() -> None:
    with pytest.raises(UnsupportedProvider, match="rss"):
        SourceProviderRegistry().validate("rss", {"url": "https://example.com/feed"})


def test_channel_registry_validates_telegram_without_exposing_token_field() -> None:
    result = ChannelProviderRegistry().validate(
        "telegram", {"chat_id": "  -100123456  "}
    )

    assert result == {"chat_id": "-100123456"}
    assert "token" not in result


def test_channel_registry_rejects_blank_chat_id() -> None:
    with pytest.raises(ValueError, match="chat_id"):
        ChannelProviderRegistry().validate("telegram", {"chat_id": "  "})
