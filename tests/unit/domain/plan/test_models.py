"""Правила слота контент-плана.

Календарь показывает восемь статусов, и ошибка в их выводе видна пользователю
сразу: слот с готовым постом обязан показывать состояние поста, а не своё.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from postify.domain.plan.models import (
    ContentPlanSlot,
    InvalidSlotTransition,
    MAX_PLAN_RANGE_DAYS,
    PlanValidationError,
    PostAlreadyGenerated,
    SlotStatus,
    SlotTopicRequired,
    generation_start,
    slot_status,
    validate_range,
    validate_transition,
)


PUBLISH_AT = datetime(2026, 10, 9, 18, tzinfo=UTC)


def _slot(**overrides) -> ContentPlanSlot:
    values = {
        "id": 41,
        "project_id": 3,
        "publish_at": PUBLISH_AT,
        "generate_at": generation_start(PUBLISH_AT, 1440),
        "rubric_id": 7,
        "topic": "Ошибки при хранении зерна",
        "status": SlotStatus.PLANNED.value,
    }
    values.update(overrides)
    return ContentPlanSlot(**values)


def test_generation_starts_the_lead_time_before_publication() -> None:
    assert generation_start(PUBLISH_AT, 1440) == datetime(2026, 10, 8, 18, tzinfo=UTC)
    assert generation_start(PUBLISH_AT, 0) == PUBLISH_AT
    assert generation_start(PUBLISH_AT, 90) == datetime(2026, 10, 9, 16, 30, tzinfo=UTC)


def test_generation_start_refuses_naive_time_and_negative_lead() -> None:
    # Поломка: без таймзоны запас времени считается от чужого часового пояса.
    with pytest.raises(PlanValidationError, match="часовой пояс"):
        generation_start(datetime(2026, 10, 9, 18), 1440)
    with pytest.raises(PlanValidationError):
        generation_start(PUBLISH_AT, -10)


def test_slot_without_topic_cannot_be_planned() -> None:
    assert _slot(topic="", status=SlotStatus.NO_TOPIC.value).status == "no_topic"
    with pytest.raises(PlanValidationError, match="no_topic"):
        _slot(topic="   ")


def test_slot_requires_aware_publication_time() -> None:
    with pytest.raises(PlanValidationError, match="publish_at"):
        _slot(publish_at=datetime(2026, 10, 9, 18))


@pytest.mark.parametrize(
    ("post_status", "expected"),
    (
        ("generating", SlotStatus.GENERATING),
        ("needs_review", SlotStatus.NEEDS_REVIEW),
        ("approved", SlotStatus.APPROVED),
        ("published", SlotStatus.PUBLISHED),
        ("failed", SlotStatus.FAILED),
        # Отклонённый пост возвращает слот в план: тема осталась.
        ("rejected", SlotStatus.PLANNED),
    ),
)
def test_status_follows_the_post_once_it_exists(post_status: str, expected) -> None:
    assert slot_status("planned", post_status, topic="Тема") is expected


def test_status_without_post_follows_the_topic() -> None:
    assert slot_status("planned", None, topic="") is SlotStatus.NO_TOPIC
    assert slot_status("no_topic", None, topic="Тема") is SlotStatus.PLANNED


def test_skip_is_a_human_decision_and_survives_a_ready_post() -> None:
    assert slot_status("skipped", "needs_review", topic="Тема") is SlotStatus.SKIPPED


def test_published_slot_cannot_be_skipped() -> None:
    validate_transition(SlotStatus.PLANNED, SlotStatus.SKIPPED)
    with pytest.raises(InvalidSlotTransition):
        validate_transition(SlotStatus.PUBLISHED, SlotStatus.SKIPPED)


def test_topic_of_a_generated_slot_is_not_editable() -> None:
    # Поломка: правка темы разошлась бы с уже написанным постом.
    with pytest.raises(PostAlreadyGenerated):
        _slot(post_id=77).ensure_topic_editable()
    _slot().ensure_topic_editable()


def test_generation_requires_a_topic() -> None:
    with pytest.raises(SlotTopicRequired):
        _slot(topic="", status=SlotStatus.NO_TOPIC.value).ensure_generatable()


def test_plan_range_is_limited_to_the_contract_window() -> None:
    validate_range(date(2026, 10, 1), date(2026, 10, 31))
    validate_range(
        date(2026, 1, 1), date(2026, 1, 1) + timedelta(days=MAX_PLAN_RANGE_DAYS - 1)
    )

    with pytest.raises(PlanValidationError, match="92"):
        validate_range(
            date(2026, 1, 1), date(2026, 1, 1) + timedelta(days=MAX_PLAN_RANGE_DAYS)
        )
    with pytest.raises(PlanValidationError, match="раньше"):
        validate_range(date(2026, 10, 31), date(2026, 10, 1))
