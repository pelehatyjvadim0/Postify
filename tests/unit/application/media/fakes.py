"""Подставные зависимости сценариев пула изображений.

Репозиторий в памяти повторяет ровно тот контракт, которым пользуются
сценарии: заведение актива с разрешением дубля по хешу, запись подписи и
отметка неудачи. Шлюз вызовов модели подставной, потому что проверяется
поведение сценария, а не провайдер.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from PIL import Image

from postify.application.ai.gateway import (
    EMBEDDING_DIMENSIONS,
    CallResult,
    ModelCallError,
)


NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
CAPTION = "Зернохранилище, металлические силосы, закат"


def png(color: tuple[int, int, int] = (10, 120, 60), size=(64, 48)) -> bytes:
    """Настоящий PNG: пул проверяет формат заголовком, а не словами клиента."""
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeMediaRepository:
    """Пул одного проекта в памяти."""

    def __init__(self) -> None:
        self.assets: dict[int, dict[str, object]] = {}
        self._by_hash: dict[str, int] = {}
        self._next_id = 1

    def create(self, *, content_hash: str, **fields) -> tuple[int, bool]:
        existing = self._by_hash.get(content_hash)
        if existing is not None:
            return existing, False
        asset_id = self._next_id
        self._next_id += 1
        self._by_hash[content_hash] = asset_id
        self.assets[asset_id] = {
            "content_hash": content_hash,
            "caption": None,
            "caption_model": None,
            "caption_status": "pending",
            "embedding": None,
            **fields,
        }
        return asset_id, True

    def save_caption(self, asset_id, *, caption, caption_model, embedding, now):
        asset = self.assets[asset_id]
        asset["caption"] = caption
        asset["caption_model"] = caption_model
        asset["embedding"] = None if embedding is None else tuple(embedding)
        asset["caption_status"] = "pending" if embedding is None else "ready"

    def mark_caption_failed(self, asset_id) -> None:
        self.assets[asset_id]["caption_status"] = "failed"

    def file(self, asset_id, *, thumb: bool) -> tuple[str, str]:
        asset = self.assets[asset_id]
        return str(asset["file_path"]), str(asset["mime"])

    def ids_captioned_by(self, caption_model: str) -> tuple[int, ...]:
        return tuple(
            asset_id
            for asset_id, asset in sorted(self.assets.items())
            if asset["caption_model"] == caption_model
        )

    def shortlist(self, embedding, *, now, limit):  # pragma: no cover - не нужен
        raise NotImplementedError


class FakeGateway:
    """Шлюз с предсказуемым ответом; ``fails`` роняет нужный вид вызова."""

    def __init__(
        self,
        *,
        caption: str = CAPTION,
        model: str = "mock",
        fails: frozenset[str] = frozenset(),
    ) -> None:
        self.caption = caption
        self.model = model
        self.fails = fails
        self.calls: list[tuple[str, str]] = []

    def caption_image(self, image_path: Path, *, context) -> CallResult:
        self.calls.append(("caption", context.purpose))
        if "caption" in self.fails:
            raise ModelCallError("provider_not_configured", "GEMINI_API_KEY не задан")
        return self._result(text=self.caption, purpose=context.purpose)

    def embed(self, text: str, *, context) -> CallResult:
        self.calls.append(("embed", context.purpose))
        if "embed" in self.fails:
            raise ModelCallError("provider_unavailable", "Провайдер недоступен")
        return self._result(
            embedding=tuple(float(index % 7) for index in range(EMBEDDING_DIMENSIONS)),
            purpose=context.purpose,
        )

    def _result(self, *, purpose: str, text=None, embedding=None) -> CallResult:
        return CallResult(
            text=text,
            embedding=embedding,
            provider=self.model,
            model=self.model,
            purpose=purpose,
            started_at=NOW,
            finished_at=NOW,
        )
