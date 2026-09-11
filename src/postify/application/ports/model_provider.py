"""Контракт провайдера модели: один транспорт — один провайдер.

Провайдер умеет ровно то, что умеет его транспорт. Codex CLI отдаёт только
текст, OpenRouter по HTTP — текст, подпись к изображению и эмбеддинг. Поэтому
неподдерживаемая операция не молчит и не возвращает пустышку, а поднимает
``ModelCallError("provider_unavailable")``: вызывающая сторона обязана узнать,
что операция не выполнена, а не получить правдоподобный мусор.

Ошибка вызова живёт здесь же, рядом с контрактом, и переэкспортируется шлюзом
(``application.ai.gateway``), чтобы адаптеры не зависели от шлюза, а шлюз
оставался единственным импортом для вызывающей стороны.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ModelCallError(RuntimeError):
    """Единственный тип ошибки вызова модели.

    Вызывающая сторона не должна знать, какой провайдер упал и почему именно:
    смена провайдера не должна заставлять переписывать обработку ошибок.
    Коды: ``codex_failed`` и прочие ``codex_*`` от CLI, ``provider_unavailable``
    (провайдер не умеет операцию либо не отвечает), ``provider_not_configured``
    (нет ключа), ``invalid_output`` (ответ пришёл, но он непригоден),
    ``provider_failed`` (провайдер упал неожиданно).
    """

    def __init__(self, code: str = "provider_unavailable", reason: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.reason = reason


class ModelProvider(Protocol):
    """Транспорт до модели. Ни промптов, ни разбора задачи внутри нет."""

    @property
    def name(self) -> str:
        """Имя провайдера: ``codex``, ``openrouter``, ``mock``."""

    @property
    def model(self) -> str:
        """Имя модели по умолчанию. Попадает в результат вызова как есть:
        по нему потом ищут и перевыпускают всё, что сделала заглушка."""

    def complete(
        self,
        prompt: str,
        *,
        output_schema: dict[str, object] | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> str: ...

    def caption_image(self, image_path: Path) -> str: ...

    def embed(self, text: str) -> tuple[float, ...]: ...
