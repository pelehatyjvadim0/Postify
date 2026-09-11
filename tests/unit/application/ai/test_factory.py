from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

from postify.adapters.ai.codex_provider import CodexModelProvider
from postify.adapters.ai.gemini_provider import GeminiModelProvider
from postify.adapters.ai.mock_provider import MockModelProvider
from postify.application.ai.factory import build_model_gateway, resolve_media_provider
from postify.application.ai.gateway import CallContext, ModelCallError
from postify.config import Settings


DATABASE_URL = "postgresql+psycopg://postify:password@localhost:5432/postify"


def _settings(**overrides) -> Settings:
    values = {
        "database_url": DATABASE_URL,
        "content_media_dir": Path("/var/lib/postify/media"),
    }
    values.update(overrides)
    return Settings(**values)


def _build(settings: Settings, tmp_path: Path):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    return build_model_gateway(
        settings,
        runner=lambda *args, **kwargs: None,
        http_client=client,
        repository_cwd=tmp_path,
    )


def test_settings_default_media_provider_is_auto() -> None:
    assert _settings().ai_media_provider == "auto"


@pytest.mark.parametrize(
    ("provider", "key", "expected"),
    [
        ("auto", None, "mock"),
        ("auto", "", "mock"),
        ("auto", "  ", "mock"),
        ("auto", "secret", "gemini"),
        ("mock", "secret", "mock"),
        ("gemini", None, "gemini"),
    ],
)
def test_resolve_media_provider(provider: str, key: str | None, expected: str) -> None:
    settings = _settings(ai_media_provider=provider, gemini_api_key=key)

    assert resolve_media_provider(settings) == expected


def test_auto_without_key_builds_mock_and_warns(tmp_path: Path, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="postify.application.ai.factory"):
        gateway = _build(_settings(), tmp_path)

    assert isinstance(gateway.text_provider, CodexModelProvider)
    assert isinstance(gateway.media_provider, MockModelProvider)
    assert gateway.embed("x", context=CallContext("embedding")).model == "mock"
    assert any("заглушка" in record.getMessage() for record in caplog.records)


def test_auto_with_key_builds_gemini_without_warning(tmp_path: Path, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="postify.application.ai.factory"):
        gateway = _build(_settings(gemini_api_key="secret"), tmp_path)

    assert isinstance(gateway.media_provider, GeminiModelProvider)
    assert isinstance(gateway.text_provider, CodexModelProvider)
    assert caplog.records == []


def test_forced_mock_ignores_key(tmp_path: Path) -> None:
    gateway = _build(_settings(gemini_api_key="secret", ai_media_provider="mock"), tmp_path)

    assert isinstance(gateway.media_provider, MockModelProvider)


def test_forced_gemini_without_key_fails_at_build(tmp_path: Path) -> None:
    with pytest.raises(ModelCallError) as caught:
        _build(_settings(ai_media_provider="gemini"), tmp_path)

    assert caught.value.code == "provider_not_configured"


def test_gemini_text_analyzer_shares_one_provider(tmp_path: Path) -> None:
    gateway = _build(
        _settings(content_analyzer="gemini", gemini_api_key="secret"), tmp_path
    )

    assert isinstance(gateway.text_provider, GeminiModelProvider)
    assert gateway.media_provider is gateway.text_provider


def test_codex_text_provider_takes_content_profile(tmp_path: Path) -> None:
    gateway = _build(
        _settings(content_model="gpt-test", content_reasoning_effort="high"), tmp_path
    )

    assert gateway.text_provider.model == "gpt-test"
