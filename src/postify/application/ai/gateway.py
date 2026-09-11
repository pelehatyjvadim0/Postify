"""Единая точка вызова модели (решение Р16 трейса, раздел 10).

Все обращения к модели — генерация, судья, извлечение фактов, vision, подпись
к изображению, эмбеддинг, вывод правил — идут через ``ModelGateway``. Ни один
адаптер и ни одно действие не зовут провайдера напрямую. Причина одна: учёт
расхода и биллинг по пользователям должны подключаться позже одной правкой —
хуком завершения вызова, — а не поиском всех мест, где дёргают модель.

Сейчас хук ``on_call_finished`` ничего не делает. Осознанный компромисс: пока
он пуст, исторических данных о расходе не копится и восстановить их задним
числом будет неоткуда.

Размерность эмбеддинга ``EMBEDDING_DIMENSIONS`` зафиксирована здесь, потому что
её хранит колонка pgvector пула изображений. Заглушка и настоящий провайдер
обязаны отдавать вектор ровно этой длины — иначе появление настоящего ключа
потребует миграции и перевыпуска всех векторов. Шлюз проверяет длину сам и не
доверяет провайдеру.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from postify.application.ports.model_provider import ModelCallError, ModelProvider


__all__ = [
    "EMBEDDING_DIMENSIONS",
    "PURPOSES",
    "CallContext",
    "CallResult",
    "ModelCallError",
    "ModelGateway",
    "on_call_finished",
]

LOGGER = logging.getLogger(__name__)

# Решение, которое нельзя менять потом: см. docstring модуля.
EMBEDDING_DIMENSIONS = 768

# Назначения вызова из контракта API, раздел 2.
PURPOSES = frozenset(
    {"generate", "judge", "claims", "vision", "caption", "embedding", "derive_rules"}
)


@dataclass(frozen=True, slots=True)
class CallContext:
    """Кто и зачем вызывает модель. Нужен хуку учёта, а не провайдеру."""

    purpose: str
    project_id: int | None = None
    user_id: int | None = None

    def __post_init__(self) -> None:
        if self.purpose not in PURPOSES:
            raise ValueError("Неизвестное назначение вызова модели")


@dataclass(frozen=True, slots=True)
class CallResult:
    """Результат вызова с честной подписью, кто его сделал.

    ``model`` берётся у провайдера как есть: у заглушки это ``"mock"``, и именно
    по этому значению потом находят и перевыпускают всё, что она сделала.
    При падении вызова хук получает результат с ``text`` и ``embedding``
    равными ``None`` — так учёт видит и неудачные обращения.
    """

    text: str | None
    embedding: tuple[float, ...] | None
    provider: str
    model: str
    purpose: str
    started_at: datetime
    finished_at: datetime


CallFinishedHook = Callable[[CallResult], None]


def on_call_finished(result: CallResult) -> None:
    """Хук завершения вызова. Сюда позже встанет учёт расхода и биллинг."""
    return None


class ModelGateway:
    """Шлюз: текстовый провайдер плюс провайдер медиа (vision и эмбеддинги).

    Два провайдера, а не один, потому что Codex CLI не умеет ни vision, ни
    эмбеддинги (трейс, раздел 5). Провайдер медиа может отсутствовать — тогда
    подпись и эмбеддинг отвечают ``provider_not_configured``.
    """

    def __init__(
        self,
        text_provider: ModelProvider,
        media_provider: ModelProvider | None = None,
        *,
        on_call_finished: CallFinishedHook = on_call_finished,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._text = text_provider
        self._media = media_provider
        self._on_call_finished = on_call_finished
        self._now = clock

    @property
    def text_provider(self) -> ModelProvider:
        return self._text

    @property
    def media_provider(self) -> ModelProvider | None:
        return self._media

    def complete(
        self,
        prompt: str,
        *,
        context: CallContext,
        output_schema: dict[str, object] | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> CallResult:
        provider = self._text
        return self._call(
            context,
            provider,
            model or provider.model,
            lambda: (
                provider.complete(
                    prompt,
                    output_schema=output_schema,
                    model=model,
                    reasoning_effort=reasoning_effort,
                ),
                None,
            ),
        )

    def caption_image(self, image_path: Path, *, context: CallContext) -> CallResult:
        provider = self._require_media()
        return self._call(
            context,
            provider,
            provider.model,
            lambda: (provider.caption_image(Path(image_path)), None),
        )

    def embed(self, text: str, *, context: CallContext) -> CallResult:
        provider = self._require_media()
        return self._call(
            context, provider, provider.model, lambda: (None, provider.embed(text))
        )

    def _require_media(self) -> ModelProvider:
        if self._media is None:
            raise ModelCallError(
                "provider_not_configured", "Провайдер vision и эмбеддингов не задан"
            )
        return self._media

    def _call(
        self,
        context: CallContext,
        provider: ModelProvider,
        model: str,
        operation: Callable[[], tuple[str | None, tuple[float, ...] | None]],
    ) -> CallResult:
        """Единственный путь любого вызова: замер времени, проверка, хук.

        Хук вызывается ровно один раз и при успехе, и при падении — иначе
        учёт расхода потеряет неудачные обращения, которые тоже стоят денег.
        """
        started = self._now()
        text: str | None = None
        embedding: tuple[float, ...] | None = None
        try:
            text, embedding = operation()
            _validate(text, embedding)
        except ModelCallError:
            self._finish(context, provider, model, None, None, started)
            raise
        except Exception as error:
            # Провайдер не должен ронять вызывающую сторону чужим типом ошибки.
            self._finish(context, provider, model, None, None, started)
            raise ModelCallError("provider_failed", type(error).__name__) from error
        return self._finish(context, provider, model, text, embedding, started)

    def _finish(
        self,
        context: CallContext,
        provider: ModelProvider,
        model: str,
        text: str | None,
        embedding: tuple[float, ...] | None,
        started: datetime,
    ) -> CallResult:
        result = CallResult(
            text=text,
            embedding=embedding,
            provider=provider.name,
            model=model,
            purpose=context.purpose,
            started_at=started,
            finished_at=self._now(),
        )
        try:
            self._on_call_finished(result)
        except Exception:
            # Учёт не должен ломать сам вызов и тем более маскировать его ошибку.
            LOGGER.exception("Хук завершения вызова модели упал")
        return result


def _validate(text: str | None, embedding: tuple[float, ...] | None) -> None:
    if embedding is not None:
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise ModelCallError(
                "invalid_output",
                f"Размерность эмбеддинга {len(embedding)}, ожидалась {EMBEDDING_DIMENSIONS}",
            )
        return
    if not isinstance(text, str) or not text.strip():
        raise ModelCallError("invalid_output", "Модель вернула пустой ответ")
