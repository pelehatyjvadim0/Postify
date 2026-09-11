"""Сценарии слота плана без базы.

Проверяются два конфликта контракта — правка темы сгенерированного слота и
генерация без темы — и то, что ``generate_at`` пересчитывается вместе с
временем публикации.
"""

from datetime import UTC, date, datetime

import pytest

from postify.application.plan.manage_slots import ManagePlan
from postify.application.plan.service import PlanService
from postify.domain.plan.models import (
    ContentPlanSlot,
    PlanValidationError,
    PostAlreadyGenerated,
    SlotTopicRequired,
)
from postify.infrastructure.repositories.sqlalchemy_plan import (
    PlanSlotRow,
    ProjectPlanSettings,
)


NOW = datetime(2026, 10, 1, 9, tzinfo=UTC)
PUBLISH_AT = datetime(2026, 10, 9, 15, tzinfo=UTC)


class MemoryPlan:
    """Репозиторий одного проекта: пишет в память и запоминает вызовы."""

    def __init__(self, *, topic: str = "Хранение зерна", post_id: int | None = None) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.row = PlanSlotRow(
            slot=ContentPlanSlot(
                id=41,
                project_id=3,
                publish_at=PUBLISH_AT,
                generate_at=datetime(2026, 10, 8, 15, tzinfo=UTC),
                rubric_id=7,
                topic=topic,
                status="planned" if topic else "no_topic",
                post_id=post_id,
            ),
            rubric_name="Подборка",
            post_status="needs_review" if post_id else None,
            post_excerpt="Влажность выше 14%" if post_id else None,
            post_media=bool(post_id),
        )

    def settings(self) -> ProjectPlanSettings:
        return ProjectPlanSettings("Europe/Moscow", 1440, "review")

    def list_range(self, *, date_from, date_to, timezone):
        self.calls.append(("list", date_from, date_to, timezone))
        return (self.row,)

    def get(self, slot_id: int) -> PlanSlotRow:
        if slot_id != self.row.slot.id:
            raise LookupError(slot_id)
        return self.row

    def create(self, **values) -> PlanSlotRow:
        self.calls.append(("create", values))
        return self.row

    def update(self, slot_id, *, values, now) -> PlanSlotRow:
        self.calls.append(("update", slot_id, values, now))
        return self.row

    def delete(self, slot_id) -> None:
        self.calls.append(("delete", slot_id))

    def skip(self, slot_id, *, now) -> PlanSlotRow:
        self.calls.append(("skip", slot_id, now))
        return self.row

    def due_generations(self, *, now):
        return (self.row.slot,)


def plan(repository) -> ManagePlan:
    return ManagePlan(repository, clock=lambda: NOW)


def service(repository, submitted: list | None = None) -> PlanService:
    def submit(project_id: int, slot_id: int) -> int:
        (submitted if submitted is not None else []).append((project_id, slot_id))
        return 1841

    return PlanService(
        lambda project_id: repository, clock=lambda: NOW, submit_generation=submit
    )


def test_create_computes_generation_start_from_the_project_lead() -> None:
    repository = MemoryPlan()

    plan(repository).create({"publish_at": PUBLISH_AT, "topic": "Тема", "rubric_id": 7})

    name, values = repository.calls[0]
    assert name == "create"
    assert values["generate_at"] == datetime(2026, 10, 8, 15, tzinfo=UTC)
    assert values["status"] == "planned"


def test_create_without_topic_stands_in_the_calendar_as_no_topic() -> None:
    repository = MemoryPlan()

    plan(repository).create({"publish_at": PUBLISH_AT})

    _, values = repository.calls[0]
    assert values["topic"] == ""
    assert values["status"] == "no_topic"


def test_moving_publication_moves_generation_with_it() -> None:
    repository = MemoryPlan()
    moved = datetime(2026, 10, 11, 15, tzinfo=UTC)

    plan(repository).update(41, {"publish_at": moved})

    _, _, values, _ = repository.calls[0]
    assert values["publish_at"] == moved
    assert values["generate_at"] == datetime(2026, 10, 10, 15, tzinfo=UTC)


def test_clearing_the_topic_returns_the_slot_to_no_topic() -> None:
    repository = MemoryPlan()

    plan(repository).update(41, {"topic": "  "})

    _, _, values, _ = repository.calls[0]
    assert values == {"topic": "", "status": "no_topic"}


def test_topic_of_a_generated_slot_is_a_conflict_and_writes_nothing() -> None:
    # Поломка: пост уже написан по старой теме, сверка фактов развалилась бы.
    repository = MemoryPlan(post_id=77)

    with pytest.raises(PostAlreadyGenerated):
        plan(repository).update(41, {"topic": "Другая тема"})

    assert repository.calls == []


def test_publication_time_of_a_generated_slot_is_still_editable() -> None:
    repository = MemoryPlan(post_id=77)

    plan(repository).update(41, {"publish_at": datetime(2026, 10, 11, 15, tzinfo=UTC)})

    assert repository.calls[0][0] == "update"


def test_generation_without_a_topic_is_refused_before_the_operation() -> None:
    repository = MemoryPlan(topic="")
    submitted: list = []

    with pytest.raises(SlotTopicRequired):
        service(repository, submitted).generate(3, 41)

    assert submitted == []


def test_generation_of_a_slot_with_a_topic_returns_the_operation() -> None:
    repository = MemoryPlan()
    submitted: list = []

    accepted = service(repository, submitted).generate(3, 41)

    assert accepted == {"operation_id": 1841, "status": "running"}
    assert submitted == [(3, 41)]
    # Статус в generating переводит трек генерации: обработчика ещё нет.
    assert repository.calls == []


def test_unknown_field_is_rejected_before_the_repository() -> None:
    repository = MemoryPlan()

    with pytest.raises(PlanValidationError, match="status"):
        plan(repository).create({"publish_at": PUBLISH_AT, "status": "approved"})

    assert repository.calls == []


def test_slot_of_another_project_is_not_reachable() -> None:
    repository = MemoryPlan()

    for call in (
        lambda: plan(repository).update(404, {"topic": "Тема"}),
        lambda: plan(repository).delete(404),
        lambda: plan(repository).skip(404),
    ):
        with pytest.raises(LookupError):
            call()

    assert repository.calls == []


def test_view_shows_the_post_card_and_project_timezone() -> None:
    repository = MemoryPlan(post_id=77)

    [slot] = service(repository).list(3, date_from=date(2026, 10, 1), date_to=date(2026, 10, 31))

    assert slot["publish_at"].utcoffset().total_seconds() == 3 * 3600
    assert slot["generate_at"].utcoffset().total_seconds() == 3 * 3600
    assert slot["status"] == "needs_review"
    assert slot["rubric"] == {"id": 7, "name": "Подборка"}
    assert slot["post"]["id"] == 77
    assert slot["post"]["media_thumb_url"] == "/api/projects/3/posts/77/media"
    # Заголовок и отчёт проверок приносят свои треки.
    assert slot["post"]["title"] is None
    assert slot["post"]["checks_summary"] is None


def test_view_without_a_post_keeps_the_card_empty() -> None:
    repository = MemoryPlan()

    [slot] = service(repository).list(3, date_from=date(2026, 10, 1), date_to=date(2026, 10, 2))

    assert slot["post"] is None
    assert slot["status"] == "planned"
