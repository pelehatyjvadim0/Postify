"""Шортлист: пустой пул — явный отказ, а не тихий повтор (риск Р3)."""

from __future__ import annotations

import pytest

from postify.application.media.models import MediaAsset, MediaCandidate
from postify.application.media.shortlist import MediaPoolEmpty, MediaShortlist

from .fakes import NOW, FakeGateway


PROJECT_ID = 3


class StubRepository:
    def __init__(self, candidates: tuple[MediaCandidate, ...]) -> None:
        self._candidates = candidates
        self.queries: list[tuple[int, int]] = []

    def shortlist(self, embedding, *, now, limit):
        self.queries.append((len(tuple(embedding)), limit))
        return self._candidates


def _asset(asset_id: int) -> MediaAsset:
    return MediaAsset(
        id=asset_id,
        project_id=PROJECT_ID,
        file_path="/tmp/a.png",
        thumb_path=None,
        mime="image/png",
        bytes=10,
        width=1,
        height=1,
        content_hash="hash",
        caption="Силосы",
        caption_model="mock",
        caption_status="ready",
        has_embedding=True,
        uploaded_at=NOW,
        last_used_at=None,
        use_count=0,
        enabled=True,
        available=True,
    )


def test_shortlist_embeds_the_query_with_the_same_provider() -> None:
    repository = StubRepository((MediaCandidate(_asset(1), 0.12),))
    gateway = FakeGateway()

    candidates = MediaShortlist(
        repository, gateway, project_id=PROJECT_ID, clock=lambda: NOW
    ).execute("хранение зерна", limit=3)

    assert [item.asset.id for item in candidates] == [1]
    # Вектор запроса считает тот же провайдер, что и подписи: иначе
    # сравнивались бы векторы из разных пространств.
    assert repository.queries == [(768, 3)]
    assert ("embed", "embedding") in gateway.calls


def test_empty_pool_is_an_explicit_refusal() -> None:
    with pytest.raises(MediaPoolEmpty) as error:
        MediaShortlist(
            StubRepository(()), FakeGateway(), project_id=PROJECT_ID, clock=lambda: NOW
        ).execute("хранение зерна")

    assert str(error.value) == "media_pool_empty"
