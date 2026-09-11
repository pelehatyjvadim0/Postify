"""Посты — раздел 8 контракта API.

Перегенерация и слоты контент-плана придут своими треками: здесь только
чтение и редакторские решения, которые не требуют обращения к модели.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from postify.domain.posts.models import PostStatus
from postify.web.auth import owned_project
from postify.web.dependencies import Container
from postify.web.schemas.posts import (
    PostPatchRequest,
    PostResponse,
    PostSummaryResponse,
)
from postify.web.schemas.operations import AcceptedOperationResponse


router = APIRouter(
    prefix="/api/projects/{project_id}/posts",
    tags=["posts"],
    dependencies=[Depends(owned_project)],
)


@router.get("", response_model=list[PostSummaryResponse])
def list_posts(
    project_id: int,
    container: Container,
    status: PostStatus | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return container.api.posts(
        project_id,
        status=None if status is None else status.value,
        limit=limit,
        offset=offset,
    )


@router.get("/{post_id}", response_model=PostResponse)
def post(project_id: int, post_id: int, container: Container):
    return container.api.post(project_id, post_id)


@router.patch("/{post_id}", response_model=PostResponse)
def update_post(
    project_id: int, post_id: int, body: PostPatchRequest, container: Container
):
    return container.api.update_post(
        project_id,
        post_id,
        post_text=body.post_text,
        scheduled_at=body.scheduled_at,
    )


@router.post("/{post_id}/approve", response_model=PostResponse)
def approve_post(project_id: int, post_id: int, container: Container):
    return container.api.approve_post(project_id, post_id)


@router.post("/{post_id}/reject", response_model=PostResponse)
def reject_post(project_id: int, post_id: int, container: Container):
    return container.api.reject_post(project_id, post_id)


@router.post("/{post_id}/regenerate", response_model=AcceptedOperationResponse, status_code=202)
def regenerate_post(project_id: int, post_id: int, container: Container):
    return container.api.regenerate_post(project_id, post_id)
