"""Журнал операций и публикации — раздел 11 контракта API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from postify.web.auth import owned_project
from postify.web.dependencies import Container
from postify.web.schemas.operations import (
    AcceptedOperationResponse,
    OperationResponse,
    PublicationResponse,
)


router = APIRouter(
    prefix="/api/projects/{project_id}",
    tags=["operations"],
    dependencies=[Depends(owned_project)],
)


@router.get("/operations", response_model=list[OperationResponse])
def list_operations(
    project_id: int,
    container: Container,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return container.api.operations(project_id, limit=limit, offset=offset)


@router.get("/operations/{operation_id}", response_model=OperationResponse)
def operation(project_id: int, operation_id: int, container: Container):
    return container.api.operation(project_id, operation_id)


@router.get("/publications", response_model=list[PublicationResponse])
def list_publications(
    project_id: int,
    container: Container,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return container.api.publications(project_id, limit=limit, offset=offset)


@router.post(
    "/publications/{delivery_id}/retry",
    response_model=AcceptedOperationResponse,
    status_code=202,
)
def retry_delivery(project_id: int, delivery_id: int, container: Container):
    return container.api.retry_delivery(project_id, delivery_id)
