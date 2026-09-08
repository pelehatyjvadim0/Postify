import pytest

from postify.adapters.channels.registry import ChannelProviderRegistry
from postify.adapters.sources.registry import SourceProviderRegistry
from postify.domain.projects.models import UnsupportedProvider


def test_source_registry_normalises_telegram_group_configuration() -> None:
    result = SourceProviderRegistry().validate(
        "telegram_group", {"group_id": "  -100123  "},
    )

    assert result == {
        "group_id": "-100123",
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


def test_channel_registry_rejects_blank_username() -> None:
    with pytest.raises(ValueError, match="username"):
        ChannelProviderRegistry().validate("telegram", {"chat_id": "  "})


def test_provider_catalog_describes_configuration_without_leaking_common_model_details() -> None:
    # Break caught: frontend must hard-code provider-specific fields because bootstrap only returns provider codes.
    sources = SourceProviderRegistry().catalog()
    channels = ChannelProviderRegistry().catalog()

    assert sources == ({
        "code": "telegram_group",
        "label": "Telegram-группа",
        "fields": (
            {"name": "group_id", "label": "Группа", "type": "text", "required": True},
        ),
    },)
    assert channels == ({
        "code": "telegram",
        "label": "Telegram",
        "fields": (
            {
                "name": "chat_id",
                "label": "@username канала",
                "type": "text",
                "required": True,
                "placeholder": "@aioiai_ai_news",
            },
        ),
        "credential": {
            "name": "token",
            "label": "Токен бота",
            "input_type": "password",
        },
    },)
