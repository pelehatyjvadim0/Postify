"""Пул изображений проекта — раздел 10 контракта API.

Здесь же остаётся отдача картинки поста
(``GET /api/projects/{id}/posts/{post_id}/media``): пока пост хранит медиа у
себя, этот маршрут нужен карточке ревью и с пулом не пересекается.

Владение проектом проверяет ``owned_project`` на уровне роутера, поэтому ни
один обработчик не сверяет владельца сам: чужой ``asset_id`` недостижим, а
чужой проект отвечает 404 ещё до разбора остальных параметров пути.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile

from postify.web.auth import owned_project
from postify.web.dependencies import Container
from postify.web.errors import ApiError
from postify.web.media_api import MAX_FILES
from postify.web.schemas.media import (
    MediaAssetResponse,
    MediaPageResponse,
    MediaPatchRequest,
)
from postify.web.schemas.operations import AcceptedOperationResponse


router = APIRouter(
    prefix="/api/projects/{project_id}",
    tags=["media"],
    dependencies=[Depends(owned_project)],
)


@router.get("/posts/{post_id}/media")
def post_media(project_id: int, post_id: int, container: Container) -> Response:
    body, media_type = container.api.post_media(project_id, post_id)
    return Response(content=body, media_type=media_type)


@router.get("/media", response_model=MediaPageResponse)
def list_media(
    project_id: int,
    container: Container,
    available: bool | None = None,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=60, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=64),
):
    return container.api.media_assets(
        project_id, available=available, query=q, limit=limit, cursor=cursor
    )


@router.post("/media", response_model=AcceptedOperationResponse, status_code=202)
def upload_media(
    project_id: int,
    container: Container,
    files: list[UploadFile] = File(default_factory=list),
):
    """Загрузка пачки файлов: подпись и вектор считаются асинхронно.

    Имя файла из запроса не читается вообще: путь на диске строится из хеша
    содержимого, а тип определяется по заголовку файла, а не по тому, что
    объявил клиент.
    """
    return container.api.upload_media(project_id, _payloads(container, files))


@router.get("/media/{asset_id}/file")
def media_file(
    project_id: int,
    asset_id: int,
    container: Container,
    size: Literal["thumb", "full"] = "full",
) -> Response:
    body, media_type = container.api.media_file(project_id, asset_id, size=size)
    return Response(content=body, media_type=media_type)


@router.patch("/media/{asset_id}", response_model=MediaAssetResponse)
def update_media(
    project_id: int, asset_id: int, body: MediaPatchRequest, container: Container
):
    return container.api.update_media(
        project_id, asset_id, caption=body.caption, enabled=body.enabled
    )


@router.delete("/media/{asset_id}", status_code=204)
def delete_media(project_id: int, asset_id: int, container: Container) -> Response:
    container.api.delete_media(project_id, asset_id)
    return Response(status_code=204)


@router.post(
    "/media/{asset_id}/recaption",
    response_model=AcceptedOperationResponse,
    status_code=202,
)
def recaption_media(project_id: int, asset_id: int, container: Container):
    """Перевыпуск подписи: этим же снимается подпись, сделанная заглушкой."""
    return container.api.recaption_media(project_id, asset_id)


def _payloads(container: Container, files: list[UploadFile]) -> list[bytes]:
    """Читает файлы, отсекая слишком большой до чтения его в память."""
    if len(files) > MAX_FILES:
        raise ApiError(
            400, "media_too_many_files", f"За раз принимается до {MAX_FILES} файлов"
        )
    limit = container.api.media_upload_limit()
    payloads: list[bytes] = []
    for item in files:
        if item.size is not None and item.size > limit:
            raise ApiError(413, "media_too_large")
        payload = item.file.read(limit + 1)
        if len(payload) > limit:
            raise ApiError(413, "media_too_large")
        payloads.append(payload)
    return payloads
