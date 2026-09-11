"""Рубрики проекта — раздел 5 контракта API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from postify.web.auth import owned_project
from postify.web.dependencies import Container
from postify.web.schemas.projects import (
    RubricCreateRequest,
    RubricResponse,
    RubricUpdateRequest,
)


router = APIRouter(
    prefix="/api/projects/{project_id}/rubrics",
    tags=["rubrics"],
    dependencies=[Depends(owned_project)],
)


@router.get("", response_model=list[RubricResponse])
def list_rubrics(project_id: int, container: Container):
    return container.api.rubrics(project_id)


@router.post("", response_model=RubricResponse, status_code=201)
def create_rubric(project_id: int, body: RubricCreateRequest, container: Container):
    return container.api.create_rubric(project_id, body.model_dump())


@router.put("/{rubric_id}", response_model=RubricResponse)
def update_rubric(
    project_id: int, rubric_id: int, body: RubricUpdateRequest, container: Container
):
    return container.api.update_rubric(
        project_id, rubric_id, body.model_dump(exclude_unset=True)
    )


@router.delete("/{rubric_id}", status_code=204)
def delete_rubric(project_id: int, rubric_id: int, container: Container) -> Response:
    container.api.delete_rubric(project_id, rubric_id)
    return Response(status_code=204)
