"""Генерация и перегенерация поста с двумя попытками починки."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Protocol

from postify.application.ai.gateway import CallContext, ModelGateway
from postify.application.generation.models import (
    GENERATION_OUTPUT_SCHEMA,
    MAX_REPAIR_ITERATIONS,
    GeneratedContent,
    GenerationBrief,
    GenerationError,
    GenerationResult,
)
from postify.application.media.models import MediaCandidate
from postify.application.ports.model_provider import ModelCallError
from postify.application.ports.validation import (
    DraftMedia,
    PostDraft,
    PostValidator,
    ValidationJournal,
    ValidationReport,
)
from postify.application.prompts.compose_context import (
    PlanSlot,
    compose_generation_context,
)


LOGGER = logging.getLogger(__name__)


class GenerationRepository(Protocol):
    """Запись поста отделена от выбора изображения и вызовов модели."""

    def brief_for_slot(self, slot_id: int) -> GenerationBrief: ...

    def brief_for_post(self, post_id: int) -> GenerationBrief: ...

    def begin_generation(self, slot_id: int, *, now: datetime) -> int: ...

    def begin_regeneration(self, post_id: int, *, now: datetime) -> None: ...

    def complete(
        self,
        post_id: int,
        *,
        content: GeneratedContent,
        media: DraftMedia,
        generation: Mapping[str, object],
        status: str = "needs_review",
        now: datetime,
    ) -> None: ...

    def fail(self, post_id: int, *, now: datetime) -> None: ...


class MediaShortlistProvider(Protocol):
    def execute(
        self, query: str, *, limit: int = 5
    ) -> tuple[MediaCandidate, ...]: ...


class GeneratePost:
    """Один и тот же конвейер для первого текста и перегенерации.

    Исходная генерация имеет номер проверки 0. При блокирующем нарушении
    модель получает только список конкретных нарушений и полный исходный
    контекст; после двух починок результат всё равно сохраняется на ревью с
    ``validation_passed=false``.
    """

    def __init__(
        self,
        repository: GenerationRepository,
        gateway: ModelGateway,
        shortlist: MediaShortlistProvider,
        validator: PostValidator,
        journal: ValidationJournal,
        *,
        clock: Callable[[], datetime],
        shortlist_limit: int = 5,
        model: str | None = None,
    ) -> None:
        if type(shortlist_limit) is not int or shortlist_limit <= 0:
            raise ValueError("shortlist_limit должен быть положительным")
        self._repository = repository
        self._gateway = gateway
        self._shortlist = shortlist
        self._validator = validator
        self._journal = journal
        self._clock = clock
        self._shortlist_limit = shortlist_limit
        self._model = model

    def generate(self, slot_id: int) -> GenerationResult:
        brief = self._repository.brief_for_slot(slot_id)
        post_id = self._repository.begin_generation(slot_id, now=self._clock())
        return self._execute(post_id, brief)

    def regenerate(self, post_id: int) -> GenerationResult:
        brief = self._repository.brief_for_post(post_id)
        self._repository.begin_regeneration(post_id, now=self._clock())
        return self._execute(post_id, brief)

    def run(
        self, *, slot_id: int | None = None, post_id: int | None = None
    ) -> GenerationResult:
        """Удобный единый вход для обработчика операции/планировщика."""
        if (slot_id is None) == (post_id is None):
            raise ValueError("Укажите ровно один из slot_id или post_id")
        if slot_id is not None:
            return self.generate(slot_id)
        return self.regenerate(post_id)

    def _execute(self, post_id: int, brief: GenerationBrief) -> GenerationResult:
        try:
            # Реализация журнала из T8 очищает старые итерации при save(0).
            # Внешние журналы могут предоставить явный clear — используем его,
            # чтобы ошибка модели не оставляла в UI отчёт предыдущего запуска.
            clear = getattr(self._journal, "clear", None)
            if callable(clear):
                clear(post_id)
            candidates = self._shortlist.execute(
                brief.slot.topic, limit=self._shortlist_limit
            )
            by_id = {candidate.asset.id: candidate for candidate in candidates}
            prompt = _generation_prompt(brief, candidates)
            content, call = self._complete(brief, prompt, by_id)
            report, media = self._validate(post_id, brief, content, by_id, iteration=0)

            repairs = 0
            repair_error = None
            while not report.passed and repairs < MAX_REPAIR_ITERATIONS:
                try:
                    next_content, next_call = self._complete(
                        brief,
                        _repair_prompt(brief, candidates, content, report, repairs + 1),
                        by_id,
                    )
                except (ModelCallError, GenerationError) as error:
                    # Последний проверенный черновик остаётся на ревью вместе
                    # с блокирующим отчётом. Сбой модели не должен стирать текст.
                    repair_error = error.code
                    LOGGER.warning("Post repair failed: post_id=%s code=%s", post_id, error.code)
                    break
                repairs += 1
                content, call = next_content, next_call
                report, media = self._validate(
                    post_id, brief, content, by_id, iteration=repairs
                )

            generated_at = self._clock()
            result = GenerationResult(
                post_id=post_id,
                content=content,
                media=media,
                validation=report,
                repair_iterations=repairs,
                provider=call.provider,
                model=call.model,
                generated_at=generated_at.isoformat(),
                publication_mode=brief.publication_mode,
            )
            metadata = result.metadata(reasoning_effort=brief.reasoning_effort)
            if repair_error is not None:
                metadata["repair_error"] = repair_error
            self._repository.complete(
                post_id,
                content=content,
                media=media,
                generation=metadata,
                status=("approved" if brief.publication_mode == "auto" and report.passed else "needs_review"),
                now=generated_at,
            )
            return result
        except Exception as error:
            LOGGER.warning("Post generation failed: post_id=%s type=%s code=%s",
                           post_id, type(error).__name__, getattr(error, "code", "internal_error"))
            # Не маскируем исходную ошибку, если фиксация failed сама не удалась.
            try:
                self._repository.fail(post_id, now=self._clock())
            except Exception:
                pass
            raise

    def _complete(self, brief, prompt, candidates):
        call = self._gateway.complete(
            prompt,
            context=CallContext(
                purpose="generate",
                project_id=brief.project_id,
                user_id=brief.user_id,
            ),
            output_schema=GENERATION_OUTPUT_SCHEMA,
            model=self._model or brief.model,
            reasoning_effort=brief.reasoning_effort,
        )
        content = GeneratedContent.parse(call.text)
        if content.media_asset_id not in candidates:
            raise GenerationError(
                "media_not_in_shortlist",
                "Модель выбрала изображение вне переданного шортлиста",
            )
        return content, call

    def _validate(self, post_id, brief, content, candidates, *, iteration):
        asset = candidates[content.media_asset_id].asset
        media = DraftMedia(
            asset_id=asset.id,
            file_path=asset.file_path,
            mime=asset.mime,
            caption=asset.caption,
        )
        report = self._validator.validate(
            PostDraft(
                project_id=brief.project_id,
                post_text=content.post_text,
                slot=brief.slot,
                media=media,
                user_id=brief.user_id,
            )
        )
        self._journal.save(
            post_id, iteration=iteration, report=report, now=self._clock()
        )
        return report, media


def _generation_prompt(
    brief: GenerationBrief, candidates: Sequence[MediaCandidate]
) -> str:
    context = compose_generation_context(
        system_prompt=brief.system_prompt,
        common_prompt=brief.common_prompt,
        project_prompt=brief.project_prompt,
        slot=PlanSlot(
            publish_at=brief.slot.publish_at,
            topic=brief.slot.topic,
            rubric=brief.slot.rubric_name,
        ),
        plan=brief.plan,
    )
    rubric = brief.slot.rubric_instructions.strip()
    rubric_block = (
        f"\n\n## Инструкции текущей рубрики\n{rubric}" if rubric else ""
    )
    return (
        "Напиши готовый Telegram-пост по текущему слоту. Выбери ровно одно "
        "изображение из шортлиста. Верни только объект заданной JSON-схемы; "
        "media_asset_id обязан быть идентификатором из шортлиста.\n\n"
        f"{context}{rubric_block}\n\n"
        "## Шортлист изображений\n"
        f"{_candidates_json(candidates)}"
    )


def _repair_prompt(
    brief: GenerationBrief,
    candidates: Sequence[MediaCandidate],
    previous: GeneratedContent,
    report: ValidationReport,
    iteration: int,
) -> str:
    violations = [item.message for item in report.blocking]
    return (
        f"Почини черновик. Это итерация {iteration} из {MAX_REPAIR_ITERATIONS}. "
        "Устрани все перечисленные нарушения, не добавляя фактов вне текущего "
        "слота. Можно выбрать другое изображение, но только из того же шортлиста. "
        "Верни только объект заданной JSON-схемы.\n\n"
        f"## Нарушения\n{json.dumps(violations, ensure_ascii=False)}\n\n"
        f"## Предыдущий черновик\n{json.dumps(_content_json(previous), ensure_ascii=False)}\n\n"
        f"{_generation_prompt(brief, candidates)}"
    )


def _candidates_json(candidates: Sequence[MediaCandidate]) -> str:
    return json.dumps(
        [
            {
                "asset_id": item.asset.id,
                "caption": item.asset.caption or "",
                "distance": item.distance,
            }
            for item in candidates
        ],
        ensure_ascii=False,
    )


def _content_json(content: GeneratedContent) -> dict[str, object]:
    return {
        "post_text": content.post_text,
        "media_asset_id": content.media_asset_id,
        "media_rationale": content.media_rationale,
    }
