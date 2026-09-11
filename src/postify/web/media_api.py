"""Веб-фасад пула изображений — раздел 10 контракта API.

Отдельный класс, а не метод в ``WebApplication``: пул приносит свой конвейер
(диск, шлюз вызовов модели, журнал операций), и держать его рядом с доставкой
означало бы смешивать два несвязанных графа зависимостей.

Границы ответственности: сюда приходит уже проверенный на владение проект
(``owned_project`` стоит на роутере), здесь проверяются транспортные лимиты и
собирается представление контракта, а сами сценарии живут в
``application/media``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from postify.adapters.media.image_store import ImageStore, ImageStoreError
from postify.application.ai.factory import build_model_gateway
from postify.application.media.captioning import CaptionMedia, RecaptionAssets
from postify.application.media.upload import UploadMedia, UploadReport
from postify.domain.observability.models import OperationKind
from postify.infrastructure.repositories.sqlalchemy_media import (
    SqlAlchemyMediaRepository,
)
from postify.infrastructure.repositories.sqlalchemy_observability import (
    SqlAlchemyOperationRunRepository,
)
from postify.infrastructure.repositories.sqlalchemy_projects import (
    SqlAlchemyProjectRepository,
)
from postify.web.errors import ApiError


# Контракт, раздел 10: за один запрос принимается не больше двадцати файлов.
MAX_FILES = 20

FAILURE_CODE = "caption_media_failed"


class MediaApi:
    """Действия пула изображений для HTTP-слоя."""

    def __init__(
        self,
        session_factory,
        settings,
        *,
        operations,
        gateway=None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = session_factory
        self._settings = settings
        self._operations = operations
        self._gateway = gateway
        self._store = ImageStore(settings.content_media_dir)
        self._projects = SqlAlchemyProjectRepository(session_factory)
        self._now = clock

    # --- чтение -----------------------------------------------------------

    def media_upload_limit(self) -> int:
        """Предельный размер одного файла. Роутер отсекает по нему до чтения
        файла в память: мультипарт уже принят на диск, и загружать оттуда
        гигабайты ради ответа 413 незачем."""
        return int(self._settings.content_media_max_bytes)

    def media_assets(
        self,
        project_id: int,
        *,
        available: bool | None = None,
        query: str | None = None,
        limit: int = 60,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        page = self._repository(project_id).list(
            now=self._now(),
            available=available,
            query=query,
            limit=limit,
            cursor=cursor,
        )
        zone = self._zone(project_id)
        return {
            "items": [_asset(item, project_id, zone) for item in page.items],
            "next_cursor": page.next_cursor,
        }

    def media_asset(self, project_id: int, asset_id: int) -> dict[str, Any]:
        asset = self._repository(project_id).get(asset_id, now=self._now())
        return _asset(asset, project_id, self._zone(project_id))

    def media_counts(self, project_id: int) -> dict[str, int]:
        """``media: {total, available}`` карточки проекта, раздел 4."""
        counts = self._repository(project_id).counts(now=self._now())
        return {"total": counts.total, "available": counts.available}

    def media_file(
        self, project_id: int, asset_id: int, *, size: str = "full"
    ) -> tuple[bytes, str]:
        path, mime = self._repository(project_id).file(
            asset_id, thumb=size == "thumb"
        )
        try:
            return self._store.read(path), mime
        except ImageStoreError:
            # Файл пропал с диска: для клиента это отсутствующий объект.
            raise LookupError(asset_id) from None

    # --- правка -----------------------------------------------------------

    def update_media(
        self,
        project_id: int,
        asset_id: int,
        *,
        caption: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        asset = self._repository(project_id).update(
            asset_id, caption=caption, enabled=enabled, now=self._now()
        )
        return _asset(asset, project_id, self._zone(project_id))

    def delete_media(self, project_id: int, asset_id: int) -> None:
        """Сначала запись, потом файлы: осиротевший файл безопаснее битой ссылки."""
        file_path, thumb_path = self._repository(project_id).delete(asset_id)
        for path in (file_path, thumb_path):
            try:
                self._store.delete(path)
            except ImageStoreError:
                # Уборка не должна отменять уже выполненное удаление записи.
                pass

    # --- длительные операции ---------------------------------------------

    def upload_media(
        self, project_id: int, payloads: Sequence[bytes]
    ) -> dict[str, Any]:
        """Принимает пачку файлов и отвечает ссылкой на операцию (202).

        Лимиты проверяются до старта операции: 413 обязан прийти сразу, а не
        через поллинг.
        """
        self._validate(payloads)
        frozen = tuple(payloads)

        def work() -> UploadReport:
            return UploadMedia(
                self._repository(project_id),
                self._store,
                self._captioner(project_id),
                project_id=project_id,
                clock=self._now,
            ).execute(frozen)

        return self._accept(project_id, work, _upload_result)

    def recaption_media(self, project_id: int, asset_id: int) -> dict[str, Any]:
        """Перевыпуск подписи одного изображения (202)."""
        repository = self._repository(project_id)
        # Проверяем существование до старта операции: чужой или отсутствующий
        # asset_id обязан ответить 404, а не завести running-строку.
        repository.get(asset_id, now=self._now())

        def work():
            return RecaptionAssets(
                repository, self._captioner(project_id), project_id=project_id
            ).execute((asset_id,))

        return self._accept(project_id, work, _recaption_result)

    # --- внутреннее -------------------------------------------------------

    def _validate(self, payloads: Sequence[bytes]) -> None:
        if not payloads:
            raise ApiError(400, "media_files_required", "Не выбрано ни одного файла")
        if len(payloads) > MAX_FILES:
            raise ApiError(
                400, "media_too_many_files", f"За раз принимается до {MAX_FILES} файлов"
            )
        limit = self._settings.content_media_max_bytes
        if any(len(payload) > limit for payload in payloads):
            raise ApiError(413, "media_too_large")

    def _repository(self, project_id: int) -> SqlAlchemyMediaRepository:
        return SqlAlchemyMediaRepository(self._sessions, project_id)

    def _captioner(self, project_id: int) -> CaptionMedia:
        return CaptionMedia(
            self._repository(project_id),
            self._model_gateway(),
            project_id=project_id,
            clock=self._now,
        )

    def _model_gateway(self):
        """Шлюз собирается один раз на процесс: у него живой HTTP-клиент."""
        if self._gateway is None:
            self._gateway = build_model_gateway(self._settings)
        return self._gateway

    def _zone(self, project_id: int) -> ZoneInfo:
        return ZoneInfo(self._projects.get(project_id).timezone)

    def _accept(
        self,
        project_id: int,
        work: Callable[[], Any],
        view: Callable[[Any], dict[str, Any]],
    ) -> dict[str, Any]:
        """Заводит строку журнала и уводит работу в фон.

        Второй running ``caption_media`` на проект запрещён частичным
        уникальным индексом, поэтому параллельная загрузка отвечает 409
        ``operation_busy``, а не падает.
        """
        journal = SqlAlchemyOperationRunRepository(self._sessions, project_id)
        run_id = journal.start(
            OperationKind.CAPTION_MEDIA, now=self._now(), mode="manual", actor="user"
        )

        def run() -> None:
            try:
                report = work()
            except BaseException:
                self._fail(journal, run_id)
                raise
            payload = view(report)
            if payload.get("captioned") == 0 and payload.get("failed"):
                # Ни одной подписи и есть отказы провайдера: операция неудачна,
                # иначе UI показал бы «готово» на пустом результате.
                self._fail(journal, run_id, payload)
                return
            journal.succeed(
                run_id, outcome=report.outcome, now=self._now(), result=payload
            )

        try:
            self._operations.submit(project_id, OperationKind.CAPTION_MEDIA.value, run)
        except BaseException:
            # Строку журнала нельзя оставлять running: UI опрашивал бы её вечно.
            self._fail(journal, run_id)
            raise
        return {"operation_id": run_id, "status": "running"}

    def _fail(self, journal, run_id: int, result: dict[str, Any] | None = None) -> None:
        try:
            journal.fail(
                run_id, failure_code=FAILURE_CODE, now=self._now(), result=result
            )
        except BaseException:
            pass


def _asset(asset, project_id: int, zone: ZoneInfo) -> dict[str, Any]:
    """Представление изображения из раздела 10 плюс ``caption_model``.

    ``caption_model`` в контракте не значился, но UI обязан честно показывать,
    что подпись сделала заглушка: ``mock`` здесь — не деталь реализации, а
    предупреждение, что подбор по этому активу бессмысленный.
    """
    base = f"/api/projects/{project_id}/media/{asset.id}/file"
    return {
        "id": asset.id,
        "url": base,
        "thumb_url": f"{base}?size=thumb",
        "mime": asset.mime,
        "caption": asset.caption,
        "caption_status": asset.caption_status,
        "caption_model": asset.caption_model,
        "width": asset.width,
        "height": asset.height,
        "bytes": asset.bytes,
        "enabled": asset.enabled,
        "use_count": asset.use_count,
        "uploaded_at": asset.uploaded_at.astimezone(zone),
        "last_used_at": (
            None if asset.last_used_at is None else asset.last_used_at.astimezone(zone)
        ),
        "available": asset.available,
    }


def _upload_result(report: UploadReport) -> dict[str, Any]:
    return {
        "asset_ids": list(report.asset_ids),
        "created": report.created,
        "duplicates": report.duplicates,
        "captioned": report.captioned,
        "failed": report.failed,
        "errors": [dict(item) for item in report.errors],
    }


def _recaption_result(report) -> dict[str, Any]:
    return {
        "requested": report.requested,
        "captioned": report.captioned,
        "failed": report.failed,
        "errors": [dict(item) for item in report.errors],
    }
