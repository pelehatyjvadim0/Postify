"""Сборка контекста генерации: порядок уровней и запрет на чужую конкретику."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from postify.application.prompts.compose_context import (
    COMMON_HEADING,
    GROUNDING_RULE,
    PLAN_HEADING,
    PROJECT_HEADING,
    SYSTEM_HEADING,
    PlanSlot,
    compose_generation_context,
)


MOSCOW = timezone(timedelta(hours=3))
SLOT = PlanSlot(
    publish_at=datetime(2026, 10, 9, 18, tzinfo=MOSCOW),
    topic="Разобрать 5 ошибок при хранении зерна. Влажность 14%.",
    rubric="Подборка",
    status="planned",
)
NEIGHBOUR = PlanSlot(
    publish_at=datetime(2026, 10, 10, 18, tzinfo=MOSCOW),
    topic="Кейс фермы «Заря»: экономия 300 тысяч на сушке",
    rubric="Кейс",
    status="planned",
)


def compose(**overrides) -> str:
    values = {
        "system_prompt": "Ты SMM-специалист.",
        "common_prompt": "Пиши без канцелярита.",
        "project_prompt": "Канал про агротехнику.",
        "slot": SLOT,
        "plan": (NEIGHBOUR,),
    }
    values.update(overrides)
    return compose_generation_context(**values)


def test_levels_follow_the_agreed_order() -> None:
    # Поломка: частное уходит выше общего, и промпт проекта перебивается
    # системным — порядок уровней зафиксирован решением Р3.
    context = compose()

    positions = [
        context.index(SYSTEM_HEADING),
        context.index(COMMON_HEADING),
        context.index(PROJECT_HEADING),
        context.index(PLAN_HEADING),
    ]

    assert positions == sorted(positions)
    assert "Ты SMM-специалист." in context
    assert "Пиши без канцелярита." in context
    assert "Канал про агротехнику." in context


def test_context_forbids_borrowing_facts_from_neighbour_slots() -> None:
    # Поломка Р6: соседние слоты попадают в контекст без запрета, и агент
    # переносит их конкретику в пост.
    context = compose()

    assert GROUNDING_RULE in context
    assert "запрещено" in GROUNDING_RULE
    # Запрет читается раньше самих слотов, к которым относится.
    assert context.index(GROUNDING_RULE) < context.index(NEIGHBOUR.topic)


def test_the_rule_stays_even_without_neighbours() -> None:
    context = compose(plan=())

    assert GROUNDING_RULE in context
    assert SLOT.topic in context
    assert "Кейс фермы" not in context


def test_current_slot_is_separated_from_the_rest_of_the_plan() -> None:
    context = compose()

    assert context.index(SLOT.topic) < context.index(NEIGHBOUR.topic)
    assert "2026-10-09T18:00+03:00" in context
    assert "2026-10-10T18:00+03:00" in context
    assert "Подборка" in context


def test_empty_levels_are_skipped_with_their_headings() -> None:
    # Пустой заголовок только занимает место в контексте и сбивает модель.
    context = compose(common_prompt="", project_prompt="   ")

    assert COMMON_HEADING not in context
    assert PROJECT_HEADING not in context
    assert SYSTEM_HEADING in context
    assert PLAN_HEADING in context


def test_multiline_prompts_keep_their_line_breaks() -> None:
    # Промпт — это инструкция списком; схлопнутый в строку он теряет структуру.
    context = compose(project_prompt="Правила:\n- без эмодзи\n- до 900 знаков")

    assert "Правила:\n- без эмодзи\n- до 900 знаков" in context
