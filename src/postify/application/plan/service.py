"""Действия контент-плана для веб-слоя — раздел 7 контракта API.

Модуль отдельный, потому что фасад ``WebApplication`` общий для треков: он
только создаёт этот сервис и делегирует ему шесть методов плана.

Времена наружу отдаются в таймзоне проекта, как требует раздел 1 контракта;
база хранит их в UTC.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from postify.application.plan.manage_slots import ManagePlan
from postify.domain.plan.models import slot_status


class PlanService:
    """Слоты плана: чтение календаря, правка и постановка генерации.

    ``repository_for`` отдаёт репозиторий, уже суженный до проекта.
    ``submit_generation`` ставит операцию ``generate_post`` и возвращает её
    идентификатор — саму генерацию выполняет трек агента.
    """

    def __init__(
        self,
        repository_for: Callable[[int], Any],
        *,
        clock: Callable[[], datetime],
        submit_generation: Callable[[int, int], int],
    ) -> None:
        self._repository_for = repository_for
        self._clock = clock
        self._submit_generation = submit_generation

    def list(
        self, project_id: int, *, date_from: date, date_to: date
    ) -> list[dict[str, Any]]:
        plan, view = self._for(project_id)
        return [view(row) for row in plan.list(date_from=date_from, date_to=date_to)]

    def create(self, project_id: int, payload: dict[str, object]) -> dict[str, Any]:
        plan, view = self._for(project_id)
        return view(plan.create(payload))

    def update(
        self, project_id: int, slot_id: int, payload: dict[str, object]
    ) -> dict[str, Any]:
        plan, view = self._for(project_id)
        return view(plan.update(slot_id, payload))

    def delete(self, project_id: int, slot_id: int) -> None:
        plan, _ = self._for(project_id)
        plan.delete(slot_id)

    def skip(self, project_id: int, slot_id: int) -> dict[str, Any]:
        plan, view = self._for(project_id)
        return view(plan.skip(slot_id))

    def generate(self, project_id: int, slot_id: int) -> dict[str, Any]:
        """202 по контракту: проверки синхронны, генерация — операция."""
        plan, _ = self._for(project_id)
        slot = plan.prepare_generation(slot_id)
        return {
            "operation_id": self._submit_generation(project_id, slot.id),
            "status": "running",
        }

    def _for(self, project_id: int):
        """Один репозиторий на действие: он же кеширует настройки проекта."""
        repository = self._repository_for(project_id)
        plan = ManagePlan(repository, clock=self._clock)

        def view(row) -> dict[str, Any]:
            zone = ZoneInfo(repository.settings().timezone)
            return _slot(row, zone, project_id=project_id)

        return plan, view


def _slot(row, zone: ZoneInfo, *, project_id: int) -> dict[str, Any]:
    slot = row.slot
    return {
        "id": slot.id,
        "publish_at": slot.publish_at.astimezone(zone),
        "generate_at": slot.generate_at.astimezone(zone),
        "rubric": (
            None
            if slot.rubric_id is None
            else {"id": slot.rubric_id, "name": row.rubric_name}
        ),
        "topic": slot.topic,
        "status": slot_status(slot.status, row.post_status, topic=slot.topic).value,
        "post": _post(row, project_id=project_id),
    }


def _post(row, *, project_id: int) -> dict[str, Any] | None:
    """Карточка предпросмотра из мокапа: её данных хватает без запроса поста.

    ``title`` и ``checks_summary`` пустые: заголовка пост не хранит, а отчёт
    слоёв проверок приносит свой трек.
    """
    slot = row.slot
    if slot.post_id is None:
        return None
    return {
        "id": slot.post_id,
        "title": None,
        "excerpt": row.post_excerpt or "",
        "media_thumb_url": (
            f"/api/projects/{project_id}/posts/{slot.post_id}/media"
            if row.post_media
            else None
        ),
        "checks_summary": None,
    }
