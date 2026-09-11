"""Сборка шлюза вызовов модели из ``Settings``.

Это единственное место, где решается, кто отвечает за текст, а кто — за
vision и эмбеддинги. Текст идёт через ``CONTENT_ANALYZER`` (codex | gemini),
медиа — через ``AI_MEDIA_PROVIDER``:

- ``auto`` (по умолчанию): Gemini, если задан ``GEMINI_API_KEY``, иначе заглушка.
  Появление ключа отключает заглушку само, без правки кода и настроек;
- ``gemini``: только Gemini, без ключа сборка падает ``provider_not_configured``;
- ``mock``: заглушка принудительно, даже при ключе.

При выборе заглушки в журнал уходит предупреждение: подписи и векторы
ненастоящие, подбор изображений по ним — не рабочий поиск.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess

import httpx

from postify.adapters.ai.codex_cli import CodexCli, codex_work_dir
from postify.adapters.ai.codex_provider import CodexModelProvider
from postify.adapters.ai.gemini_provider import GeminiModelProvider
from postify.adapters.ai.mock_provider import MockModelProvider
from postify.application.ai.gateway import CallFinishedHook, ModelGateway, on_call_finished
from postify.application.ports.model_provider import ModelCallError, ModelProvider
from postify.config import Settings


LOGGER = logging.getLogger(__name__)

MOCK_WARNING = (
    "AI_MEDIA_PROVIDER=%s: подписи к изображениям и эмбеддинги делает "
    "заглушка (model=mock). Vision и семантический поиск НЕ работают; всё, что "
    "она сделает, надо перевыпустить после появления GEMINI_API_KEY."
)


def resolve_media_provider(settings: Settings) -> str:
    """``gemini`` или ``mock`` с учётом ``auto`` и наличия ключа."""
    if settings.ai_media_provider != "auto":
        return settings.ai_media_provider
    return "gemini" if _gemini_key(settings) else "mock"


def build_model_gateway(
    settings: Settings,
    *,
    runner: Callable[..., CompletedProcess[str]] = subprocess.run,
    http_client: httpx.Client | None = None,
    repository_cwd: Path | None = None,
    on_call_finished: CallFinishedHook = on_call_finished,
) -> ModelGateway:
    """Собирает шлюз. ``http_client`` создаётся лениво и живёт весь процесс.

    ``repository_cwd`` нужен только Codex — чтобы одноразовый каталог вызова
    не оказался внутри репозитория или медиа.
    """
    gemini: GeminiModelProvider | None = None

    def gemini_provider() -> GeminiModelProvider:
        nonlocal gemini, http_client
        if gemini is None:
            key = _gemini_key(settings)
            if not key:
                raise ModelCallError("provider_not_configured", "GEMINI_API_KEY не задан")
            if http_client is None:
                http_client = httpx.Client(
                    timeout=float(settings.content_analysis_timeout_seconds)
                )
            gemini = GeminiModelProvider(http_client, api_key=key)
        return gemini

    text: ModelProvider
    if settings.content_analyzer == "gemini":
        text = gemini_provider()
    else:
        repository = Path(repository_cwd) if repository_cwd is not None else Path.cwd()
        text = CodexModelProvider(
            CodexCli(
                runner,
                work_dir=codex_work_dir(repository, settings.content_media_dir),
                repository_cwd=repository,
                timeout_seconds=float(settings.content_analysis_timeout_seconds),
                model=settings.content_model,
                reasoning_effort=settings.content_reasoning_effort,
            )
        )

    media: ModelProvider
    if resolve_media_provider(settings) == "gemini":
        media = gemini_provider()
    else:
        LOGGER.warning(MOCK_WARNING, settings.ai_media_provider)
        media = MockModelProvider()

    return ModelGateway(text, media, on_call_finished=on_call_finished)


def _gemini_key(settings: Settings) -> str:
    if settings.gemini_api_key is None:
        return ""
    return settings.gemini_api_key.get_secret_value().strip()
