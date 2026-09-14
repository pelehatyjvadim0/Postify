"""Шортлист изображений для агента генерации.

Агент не выбирает из всего пула: ему дают несколько ближайших по смыслу
доступных изображений и просят обосновать выбор (трейс, раздел 8). Отбор
делает база — политика повторов и векторное расстояние в одном запросе.

Пустой шортлист — не молчаливый повтор, а явный отказ ``media_pool_empty``:
именно тихий повтор одной и той же картинки был бы риском Р3.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from postify.application.ai.gateway import CallContext
from postify.application.media.models import MediaCandidate


DEFAULT_SHORTLIST = 5


class MediaPoolEmpty(RuntimeError):
    """В пуле нет изображения, доступного по политике повторов."""

    def __init__(self) -> None:
        super().__init__("media_pool_empty")
        self.code = "media_pool_empty"
        self.reason = "Упс, не нашли доступное изображение"


class MediaShortlist:
    """Ближайшие доступные изображения проекта по тексту запроса."""

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

    def execute(
        self, query: str, *, limit: int = DEFAULT_SHORTLIST
    ) -> tuple[MediaCandidate, ...]:
        """Считает вектор запроса тем же провайдером, что и подписи.

        Иначе поиск сравнивал бы векторы из разных пространств и выдавал бы
        правдоподобный мусор.
        """
        vector = self._gateway.embed(
            query,
            context=CallContext(
                purpose="embedding",
                project_id=self._project_id,
                user_id=self._user_id,
            ),
        )
        candidates = self._repository.shortlist(
            vector.embedding, now=self._clock(), limit=limit
        )
        if not candidates:
            raise MediaPoolEmpty()
        return candidates
