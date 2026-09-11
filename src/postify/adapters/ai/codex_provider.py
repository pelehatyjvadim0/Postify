"""Codex CLI под контрактом провайдера модели: только текст.

Codex запускается как процесс и возвращает текст — ни vision-подписи, ни
эмбеддингов он не умеет (трейс, раздел 5). Поэтому обе медиа-операции честно
отвечают ``provider_unavailable``, а не пытаются что-то изобразить.
"""

from __future__ import annotations

from pathlib import Path

from postify.adapters.ai.codex_cli import CodexCallError, CodexCli
from postify.application.ports.model_provider import ModelCallError


class CodexModelProvider:
    """Обёртка над готовым транспортом ``CodexCli``."""

    name = "codex"

    def __init__(self, cli: CodexCli) -> None:
        self._cli = cli

    @property
    def model(self) -> str:
        return self._cli.model

    def complete(
        self,
        prompt: str,
        *,
        output_schema: dict[str, object] | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        try:
            return self._cli.complete(
                prompt,
                output_schema=output_schema,
                model=model,
                reasoning_effort=reasoning_effort,
            )
        except CodexCallError as error:
            # Код CLI сохраняем: он различает «упал вызов» и «нет рабочего
            # каталога», а тип ошибки наружу всё равно один.
            raise ModelCallError(error.code, error.reason) from None

    def caption_image(self, image_path: Path) -> str:
        raise ModelCallError("provider_unavailable", "Codex CLI не умеет vision")

    def embed(self, text: str) -> tuple[float, ...]:
        raise ModelCallError("provider_unavailable", "Codex CLI не умеет эмбеддинги")
