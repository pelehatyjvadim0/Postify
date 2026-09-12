"""Шов между агентом генерации и слоями проверок.

Два трека пишут по разные стороны этого файла и друг друга не видят:
генерация собирает черновик и крутит repair loop, проверки считают слои и
возвращают нарушения. Поэтому здесь только данные и протоколы — ни одной
строки поведения. Менять этот файл в одиночку нельзя: он общий.

Почему нарушение несёт текст на русском: он уходит прямо в промпт починки,
а не только в UI. Модель должна прочитать, что именно исправить, без
словаря кодов на стороне генерации.

Почему ``ValidationReport`` не знает номера итерации: одна проверка ничего не
знает о цикле, в котором её вызвали. Номер добавляет конвейер генерации,
когда складывает итоговый отчёт раздела 9 контракта.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


__all__ = [
    "LAYERS",
    "SEVERITIES",
    "DraftMedia",
    "DraftSlot",
    "PostDraft",
    "ValidationJournal",
    "ValidationReport",
    "PostValidator",
    "Violation",
]

# Слои проверок из раздела 2 контракта. Порядок значим: отчёт отдаётся в нём.
LAYERS = ("format", "rules", "grounding", "image")

# ``block`` отправляет пост на починку, ``warn`` только помечается редактору.
SEVERITIES = ("block", "warn")


@dataclass(frozen=True, slots=True)
class DraftMedia:
    """Изображение, выбранное агентом из пула проекта."""

    asset_id: int
    # Абсолютный путь на диске: слой соответствия картинки смотрит сам файл,
    # а не подпись к нему.
    file_path: str
    mime: str
    caption: str | None


@dataclass(frozen=True, slots=True)
class DraftSlot:
    """Слот плана — единственная опора слоя сверки фактов.

    Соседние слоты сюда не попадают намеренно: заимствовать из них конкретику
    запрещено (риск Р6), и проверка обязана этого не знать.
    ``publish_at`` уже переведён в таймзону проекта.
    """

    slot_id: int
    publish_at: datetime
    topic: str
    rubric_name: str = ""
    rubric_instructions: str = ""


@dataclass(frozen=True, slots=True)
class PostDraft:
    """Что именно проверяется. Собирается конвейером генерации."""

    project_id: int
    post_text: str
    slot: DraftSlot
    media: DraftMedia | None = None
    # Нужен шлюзу вызовов модели для учёта расхода; у планировщика его нет.
    user_id: int | None = None


@dataclass(frozen=True, slots=True)
class Violation:
    """Одно нарушение. ``message`` уходит в промпт починки как есть."""

    layer: str
    severity: str
    message: str

    def __post_init__(self) -> None:
        if self.layer not in LAYERS:
            raise ValueError("Неизвестный слой проверки")
        if self.severity not in SEVERITIES:
            raise ValueError("Неизвестная строгость нарушения")


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Результат одного прохода проверок.

    ``passed`` — нет ни одного нарушения строгости ``block``; предупреждения
    пост не задерживают. ``layers`` — слои в формате раздела 9 контракта, как
    они уйдут в API; конвейер их не разбирает и не переписывает.
    """

    passed: bool
    violations: tuple[Violation, ...] = ()
    layers: tuple[Mapping[str, Any], ...] = ()

    @property
    def blocking(self) -> tuple[Violation, ...]:
        return tuple(item for item in self.violations if item.severity == "block")


class PostValidator(Protocol):
    """Слои проверок. Реализация живёт в ``application/validation``."""

    def validate(self, draft: PostDraft) -> ValidationReport:
        """Все четыре слоя. Вызывается конвейером генерации на каждой итерации."""

    def validate_edit(self, draft: PostDraft) -> ValidationReport:
        """Слои 1 и 3 без обращения к модели — для ручной правки редактора.

        Только предварительная проверка; этого отчёта недостаточно для одобрения.
        Сохранение редакторской правки в приложении запускает полную validate.
        """


class ValidationJournal(Protocol):
    """Хранение отчётов проверок по итерациям."""

    def save(
        self,
        post_id: int,
        *,
        iteration: int,
        report: ValidationReport,
        now: datetime,
    ) -> None: ...

    def report(self, post_id: int) -> Mapping[str, Any] | None:
        """Отчёт раздела 9 целиком: ``{passed, iterations, layers}``.

        ``None`` — проверок для поста не было. Отдаётся по последней итерации:
        промежуточные хранятся ради разбора, а не ради показа.
        """

    def reports(self, post_ids: Sequence[int]) -> Mapping[int, Mapping[str, Any]]:
        """То же пачкой — для списка постов и календаря, без запроса на строку."""
