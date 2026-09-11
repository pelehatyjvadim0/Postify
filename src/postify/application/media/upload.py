"""Загрузка изображений в пул проекта.

Порядок шагов важен: сначала файл ложится на диск и появляется строка в базе,
и только потом идёт обращение к модели. Так изображение переживает падение
провайдера — оно уже загружено, не хватает лишь подписи.

Повторная загрузка того же содержимого не заводит вторую запись: уникальность
по ``(project_id, хеш содержимого)`` разрешает конфликт молча, а подпись у
существующего актива не трогается — она может быть уже поправлена человеком.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from postify.adapters.media.image_store import ImageStoreError, UnsupportedImage
from postify.application.media.captioning import CaptionMedia


@dataclass(frozen=True, slots=True)
class UploadReport:
    """Что получилось из пачки файлов. Уезжает в ``result`` журнала операций."""

    asset_ids: tuple[int, ...]
    created: int
    duplicates: int
    captioned: int
    failed: int
    errors: tuple[dict[str, str], ...]

    @property
    def outcome(self) -> str:
        """Слово журнала операций: пустая загрузка — ``empty``."""
        return "completed" if self.asset_ids else "empty"


class UploadMedia:
    """Сохраняет файлы, заводит активы и просит подпись у модели."""

    def __init__(
        self,
        repository,
        store,
        captioner: CaptionMedia,
        *,
        project_id: int,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._store = store
        self._captioner = captioner
        self._project_id = project_id
        self._clock = clock

    def execute(self, payloads: Sequence[bytes]) -> UploadReport:
        asset_ids: list[int] = []
        errors: list[dict[str, str]] = []
        created = duplicates = captioned = 0
        for index, payload in enumerate(payloads):
            try:
                stored = self._store.save(payload, project_id=self._project_id)
            except (UnsupportedImage, ImageStoreError) as error:
                errors.append({"file": str(index), "reason": str(error)[:300]})
                continue
            asset_id, is_new = self._repository.create(
                file_path=stored.file_path,
                thumb_path=stored.thumb_path,
                mime=stored.mime,
                bytes=stored.bytes,
                width=stored.width,
                height=stored.height,
                content_hash=stored.content_hash,
                now=self._clock(),
            )
            asset_ids.append(asset_id)
            if not is_new:
                duplicates += 1
                continue
            created += 1
            outcome = self._captioner.execute(asset_id, file_path=stored.file_path)
            if outcome.succeeded:
                captioned += 1
            else:
                errors.append({"asset_id": str(asset_id), **(outcome.error or {})})
        return UploadReport(
            asset_ids=tuple(asset_ids),
            created=created,
            duplicates=duplicates,
            captioned=captioned,
            failed=len(errors),
            errors=tuple(errors),
        )
