"""Файл картинки поста.

Пул изображений проекта с ``/media/{asset_id}/file`` принесёт свой трек; здесь
только то, что уже лежит у поста и нужно карточке ревью.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from postify.web.auth import owned_project
from postify.web.dependencies import Container


router = APIRouter(
    prefix="/api/projects/{project_id}",
    tags=["media"],
    dependencies=[Depends(owned_project)],
)


@router.get("/posts/{post_id}/media")
def post_media(project_id: int, post_id: int, container: Container) -> Response:
    body, media_type = container.api.post_media(project_id, post_id)
    return Response(content=body, media_type=media_type)
