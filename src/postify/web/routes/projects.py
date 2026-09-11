"""Проекты и канал проекта — разделы 4 контракта API.

Роутер тонкий: разбирает транспорт и зовёт действие фасада. Владение проектом
проверяет зависимость ``owned_project`` на уровне роутера, поэтому ни один
обработчик не сверяет владельца сам.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from postify.domain.auth.models import User
from postify.web.auth import current_user, owned_project
from postify.web.dependencies import Container
from postify.web.schemas.projects import (
    ChannelRequest,
    ChannelResponse,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectSummaryResponse,
    ProjectUpdateRequest,
)


CurrentUser = Annotated[User, Depends(current_user)]

collection = APIRouter(prefix="/api/projects", tags=["projects"])
router = APIRouter(
    prefix="/api/projects/{project_id}",
    tags=["projects"],
    dependencies=[Depends(owned_project)],
)


@collection.get("", response_model=list[ProjectSummaryResponse])
def list_projects(container: Container, user: CurrentUser):
    # Единственная коллекция без project_id: владельца берём из сессии сами.
    return container.api.list_projects(owner_id=user.id)


@collection.post("", response_model=ProjectResponse, status_code=201)
def create_project(
    body: ProjectCreateRequest, container: Container, user: CurrentUser
):
    return container.api.create_project(body.model_dump(), owner_id=user.id)


@router.get("", response_model=ProjectResponse)
def project(project_id: int, container: Container):
    return container.api.project(project_id)


@router.put("", response_model=ProjectResponse)
def update_project(project_id: int, body: ProjectUpdateRequest, container: Container):
    return container.api.update_project(
        project_id, body.model_dump(exclude_unset=True)
    )


@router.delete("", status_code=204)
def delete_project(project_id: int, container: Container) -> Response:
    container.api.delete_project(project_id)
    return Response(status_code=204)


@router.put("/channel", response_model=ChannelResponse)
def set_channel(project_id: int, body: ChannelRequest, container: Container):
    return container.api.set_channel(
        project_id, bot_token=body.bot_token, chat_id=body.chat_id
    )


@router.post("/channel/check", response_model=ChannelResponse)
def check_channel(project_id: int, container: Container):
    return container.api.check_channel(project_id)


@router.delete("/channel", status_code=204)
def remove_channel(project_id: int, container: Container) -> Response:
    container.api.remove_channel(project_id)
    return Response(status_code=204)
