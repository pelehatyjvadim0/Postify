"""Сборка контекста генерации из трёх уровней промптов и контент-плана.

Порядок уровней зафиксирован решением Р3 и менять его нельзя: системный
промпт сервера → общий промпт пользователя → промпт проекта → контент-план.
Каждый следующий уровень уточняет предыдущий, поэтому он и идёт ниже: модель
читает контекст сверху вниз, и частное должно стоять после общего.

Здесь же формулируется запрет на заимствование конкретики из соседних слотов
(риск Р6). Запрет обязан быть в самом тексте контекста, а не только в проверке
постфактум: слой 3 ловит нарушение, но дешевле его не допустить. Пустые уровни
пропускаются — заголовок без текста только занимает место в контексте.

Правила жанра и фактов общие с проверкой: GENERATION_VALIDATION_POLICY.
Соседний план помогает связности, но не служит источником фактов.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from postify.application.validation.policy import GENERATION_VALIDATION_POLICY


# Заголовки уровней вынесены в константы: по ним же проверяется порядок.
SYSTEM_HEADING = "## Системный промпт сервера"
COMMON_HEADING = "## Общий промпт пользователя"
PROJECT_HEADING = "## Промпт проекта"
PLAN_HEADING = "## Контент-план"

CURRENT_SLOT_HEADING = "Текущий слот — тема этого поста:"
NEIGHBOURS_HEADING = "Остальной план, только для связности:"

GROUNDING_RULE = GENERATION_VALIDATION_POLICY


@dataclass(frozen=True, slots=True)
class PlanSlot:
    """Минимум, который сборка контекста ждёт от слота контент-плана.

    Ровно то, что уже отдаёт слот в разделе 7 контракта; всё остальное
    (идентификаторы, пост, время генерации) контексту не нужно и в него не
    попадает. ``publish_at`` ожидается в таймзоне проекта — контекст ничего
    не переводит, это делает поставщик плана.
    """

    publish_at: datetime
    topic: str
    rubric: str = ""
    status: str = ""


def compose_generation_context(
    *,
    system_prompt: str,
    common_prompt: str,
    project_prompt: str,
    slot: PlanSlot,
    plan: Sequence[PlanSlot] = (),
) -> str:
    """Складывает уровни в один текст.

    ``plan`` — соседние слоты актуального плана без текущего. Порядок, в
    котором их подали, сохраняется: план читается как календарь.
    """
    blocks: list[str] = []
    for heading, text in (
        (SYSTEM_HEADING, system_prompt),
        (COMMON_HEADING, common_prompt),
        (PROJECT_HEADING, project_prompt),
    ):
        body = (text or "").strip()
        if body:
            blocks.append(f"{heading}\n{body}")
    blocks.append(_plan_block(slot, plan))
    return "\n\n".join(blocks)


def _plan_block(slot: PlanSlot, plan: Sequence[PlanSlot]) -> str:
    """Контент-план: запрет, текущий слот, соседние слоты.

    Запрет стоит до слотов, чтобы он читался раньше данных, к которым
    относится.
    """
    lines = [PLAN_HEADING, GROUNDING_RULE, "", CURRENT_SLOT_HEADING, _current(slot)]
    neighbours = [_neighbour(item) for item in plan]
    if neighbours:
        lines.extend(["", NEIGHBOURS_HEADING, *neighbours])
    return "\n".join(lines)


def _current(slot: PlanSlot) -> str:
    parts = [f"- Публикация: {_moment(slot.publish_at)}"]
    if slot.rubric:
        parts.append(f"- Рубрика: {slot.rubric}")
    parts.append(f"- Тема: {slot.topic.strip()}")
    return "\n".join(parts)


def _neighbour(slot: PlanSlot) -> str:
    """Соседний слот одной строкой: дата, рубрика, тема, статус."""
    parts = [_moment(slot.publish_at)]
    if slot.rubric:
        parts.append(slot.rubric)
    parts.append(slot.topic.strip() or "тема не задана")
    if slot.status:
        parts.append(slot.status)
    return "- " + " · ".join(parts)


def _moment(value: datetime) -> str:
    return value.isoformat(timespec="minutes")
