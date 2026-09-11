"""Сценарии слота контент-плана.

Календарь — единственное место, где назначается время публикации, поэтому
здесь же считается ``generate_at`` и проверяются два конфликта контракта:
правка темы у слота с готовым постом и генерация слота без темы.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

from postify.domain.plan.models import (
    ContentPlanSlot,
    PlanValidationError,
    SlotStatus,
    generation_start,
    normalise_topic,
    slot_status,
    status_without_post,
    validate_transition,
)


CREATE_FIELDS = frozenset({"publish_at", "rubric_id", "topic"})
PATCH_FIELDS = frozenset({"publish_at", "rubric_id", "topic"})

# Состояния, которые описывает сам слот: их пересчитывает наличие темы. Всё
# остальное приходит от поста, и трогать его правкой слота нельзя.
TOPIC_DRIVEN = frozenset({SlotStatus.NO_TOPIC, SlotStatus.PLANNED})


class ManagePlan:
    """Слоты одного проекта. Репозиторий уже сужен до его ``project_id``."""

    def __init__(self, repository, *, clock: Callable[[], datetime]) -> None:
        self._repository = repository
        self._clock = clock

    def list(self, *, date_from: date, date_to: date):
        settings = self._repository.settings()
        return self._repository.list_range(
            date_from=date_from, date_to=date_to, timezone=settings.timezone
        )

    def get(self, slot_id: int):
        return self._repository.get(slot_id)

    def create(self, payload: dict[str, object]):
        _reject_unknown(payload, CREATE_FIELDS)
        if "publish_at" not in payload:
            raise PlanValidationError("Время публикации слота обязательно")
        settings = self._repository.settings()
        publish_at = payload["publish_at"]
        topic = normalise_topic(payload.get("topic"))
        return self._repository.create(
            publish_at=publish_at,
            generate_at=generation_start(
                publish_at, settings.generation_lead_minutes
            ),
            rubric_id=payload.get("rubric_id"),
            topic=topic,
            status=status_without_post(topic).value,
            now=self._clock(),
        )

    def update(self, slot_id: int, payload: dict[str, object]):
        """Частичная правка: ``publish_at``, ``rubric_id``, ``topic``."""
        _reject_unknown(payload, PATCH_FIELDS)
        row = self._repository.get(slot_id)
        slot = row.slot
        values: dict[str, object] = {}
        if "rubric_id" in payload:
            values["rubric_id"] = payload["rubric_id"]
        if "publish_at" in payload:
            settings = self._repository.settings()
            values["publish_at"] = payload["publish_at"]
            values["generate_at"] = generation_start(
                payload["publish_at"], settings.generation_lead_minutes
            )
        if "topic" in payload:
            # Тема — вход генерации и опора слоя сверки фактов: у готового
            # поста её правка молча разошлась бы с текстом.
            slot.ensure_topic_editable()
            topic = normalise_topic(payload["topic"])
            values["topic"] = topic
            if SlotStatus(slot.status) in TOPIC_DRIVEN:
                values["status"] = status_without_post(topic).value
        if not values:
            return row
        return self._repository.update(slot_id, values=values, now=self._clock())

    def delete(self, slot_id: int) -> None:
        # Существование проверяется отдельно: чужой слот обязан дать 404 и не
        # тронуть ничего.
        self._repository.get(slot_id)
        self._repository.delete(slot_id)

    def skip(self, slot_id: int):
        row = self._repository.get(slot_id)
        status = slot_status(
            row.slot.status, row.post_status, topic=row.slot.topic
        )
        validate_transition(status, SlotStatus.SKIPPED)
        return self._repository.skip(slot_id, now=self._clock())

    def prepare_generation(self, slot_id: int) -> ContentPlanSlot:
        """Проверки перед постановкой генерации; сам запуск делает фасад.

        Статус в ``generating`` здесь не переводится: обработчика генерации
        ещё нет, и слот повис бы в этом состоянии навсегда. Переводит его тот
        трек, который умеет генерацию выполнять.
        """
        row = self._repository.get(slot_id)
        status = slot_status(
            row.slot.status, row.post_status, topic=row.slot.topic
        )
        if row.slot.topic:
            validate_transition(status, SlotStatus.GENERATING)
        row.slot.ensure_generatable()
        return row.slot

    def due_generations(self, *, now: datetime) -> tuple[ContentPlanSlot, ...]:
        return self._repository.due_generations(now=now)


def _reject_unknown(payload: dict[str, object], allowed: frozenset[str]) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise PlanValidationError(
            f"Недопустимые поля слота: {', '.join(sorted(unknown))}"
        )
