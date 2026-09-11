"""Подпись изображения и эмбеддинг подписи через шлюз вызовов модели.

Две вещи держатся здесь намеренно вместе: вектор считается по тексту подписи,
поэтому подпись без вектора бесполезна для подбора, а вектор без подписи
нечем показать человеку.

Провайдер может быть недоступен. Тогда изображение всё равно остаётся в пуле,
но с ``caption_status='failed'``: потерять загруженный файл из-за молчащего
провайдера хуже, чем показать явную ошибку (трейс, раздел 5).

Имя модели пишется в базу всегда. У заглушки это ровно ``mock`` — по этому
значению ``RecaptionAssets`` потом находит всё, что надо перевыпустить.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from postify.application.ai.gateway import CallContext, ModelCallError


@dataclass(frozen=True, slots=True)
class CaptionOutcome:
    """Итог подписи одного изображения."""

    asset_id: int
    caption_model: str | None
    error: dict[str, str] | None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass(frozen=True, slots=True)
class RecaptionReport:
    """Итог перевыпуска пачки подписей."""

    project_id: int
    requested: int
    captioned: int
    failed: int
    errors: tuple[dict[str, str], ...]


class CaptionMedia:
    """Подписывает одно изображение и считает вектор его подписи."""

    def __init__(
        self,
        repository,
        gateway,
        *,
        project_id: int,
        user_id: int | None = None,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._project_id = project_id
        self._user_id = user_id
        self._clock = clock

    def execute(self, asset_id: int, *, file_path: str) -> CaptionOutcome:
        try:
            caption = self._gateway.caption_image(
                Path(file_path), context=self._context("caption")
            )
        except ModelCallError as error:
            self._repository.mark_caption_failed(asset_id)
            return CaptionOutcome(asset_id, None, _details(error))

        text = (caption.text or "").strip()
        if not text:
            # Пустая подпись — тот же отказ: подписывать нечем и вектор не с чего.
            self._repository.mark_caption_failed(asset_id)
            return CaptionOutcome(
                asset_id,
                caption.model,
                {"code": "invalid_output", "reason": "Пустая подпись"},
            )

        try:
            vector = self._gateway.embed(text, context=self._context("embedding"))
        except ModelCallError as error:
            # Подпись получена, вектор — нет: текст сохраняем, чтобы работа
            # vision не пропала, но в подбор изображение не пускаем.
            self._save(asset_id, text, caption.model, None)
            self._repository.mark_caption_failed(asset_id)
            return CaptionOutcome(asset_id, caption.model, _details(error))

        self._save(asset_id, text, caption.model, vector.embedding)
        return CaptionOutcome(asset_id, caption.model, None)

    def _save(
        self,
        asset_id: int,
        caption: str,
        model: str,
        embedding: Sequence[float] | None,
    ) -> None:
        self._repository.save_caption(
            asset_id,
            caption=caption,
            caption_model=model,
            embedding=embedding,
            now=self._clock(),
        )

    def _context(self, purpose: str) -> CallContext:
        return CallContext(
            purpose=purpose, project_id=self._project_id, user_id=self._user_id
        )


class RecaptionAssets:
    """Перевыпуск подписей: точка перехода с заглушки на настоящего провайдера.

    Одна и та же операция обслуживает кнопку «перевыпустить» у одного
    изображения и массовый прогон после появления ключа: во втором случае
    список идентификаторов берётся выборкой по ``caption_model``.
    """

    def __init__(self, repository, captioner: CaptionMedia, *, project_id: int) -> None:
        self._repository = repository
        self._captioner = captioner
        self._project_id = project_id

    def execute(self, asset_ids: Sequence[int]) -> RecaptionReport:
        captioned = 0
        errors: list[dict[str, str]] = []
        for asset_id in asset_ids:
            file_path, _ = self._repository.file(asset_id, thumb=False)
            outcome = self._captioner.execute(asset_id, file_path=file_path)
            if outcome.succeeded:
                captioned += 1
            else:
                errors.append({"asset_id": str(asset_id), **(outcome.error or {})})
        return RecaptionReport(
            project_id=self._project_id,
            requested=len(asset_ids),
            captioned=captioned,
            failed=len(errors),
            errors=tuple(errors),
        )

    def captioned_by(self, caption_model: str) -> tuple[int, ...]:
        return self._repository.ids_captioned_by(caption_model)


def _details(error: BaseException) -> dict[str, str]:
    """Код и причина отказа провайдера в виде, пригодном для журнала и UI."""
    code = getattr(error, "code", None) or "provider_unavailable"
    reason = getattr(error, "reason", None) or str(error)
    return {"code": str(code), "reason": str(reason)[:300]}
