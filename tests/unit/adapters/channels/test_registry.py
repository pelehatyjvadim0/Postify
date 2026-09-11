import pytest

from postify.adapters.channels.registry import ChannelProviderRegistry
from postify.domain.projects.models import UnsupportedProvider


def test_channel_registry_validates_telegram_without_exposing_token_field() -> None:
    result = ChannelProviderRegistry().validate(
        "telegram", {"chat_id": "  -100123456  "}
    )

    assert result == {"chat_id": "-100123456"}
    assert "token" not in result


def test_channel_registry_rejects_blank_username() -> None:
    with pytest.raises(ValueError, match="username"):
        ChannelProviderRegistry().validate("telegram", {"chat_id": "  "})


def test_channel_registry_knows_only_telegram() -> None:
    # Поломка: в реестре остаётся провайдер снесённого контура источников.
    registry = ChannelProviderRegistry()

    assert tuple(entry["code"] for entry in registry.catalog()) == ("telegram",)
    with pytest.raises(UnsupportedProvider, match="telegram_group"):
        registry.validate("telegram_group", {"group_id": "-100123"})


def test_channel_catalog_describes_configuration_for_the_frontend() -> None:
    # Поломка: фронтенд вынужден зашивать поля канала, потому что каталог их не отдаёт.
    assert ChannelProviderRegistry().catalog() == ({
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
