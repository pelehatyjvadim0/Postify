"""Контент-план — раздел 7 контракта API.

Календарь — единственное место, где назначается время публикации: время
поста берётся из его слота.

Доменные отказы плана переводятся в коды контракта здесь, на границе
транспорта: сценарии про HTTP ничего не знают.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from postify.domain.plan.models import (
    InvalidSlotTransition,
    PostAlreadyGenerated,
    SlotTimeTaken,
    SlotTopicRequired,
)
from postify.web.auth import owned_project
from postify.web.dependencies import Container
from postify.web.errors import ApiError
from postify.web.schemas.operations import AcceptedOperationResponse
from postify.web.schemas.plan import (
    GeneratePostRequest,
    SlotCreateRequest,
    SlotPatchRequest,
    SlotResponse,
)


router = APIRouter(
    prefix="/api/projects/{project_id}/plan",
    tags=["plan"],
    dependencies=[Depends(owned_project)],
)


def _translated(action: Callable[[], Any]) -> Any:
    """Отказы плана — это коды контракта, а не внутренние ошибки."""
    try:
        return action()
    except PostAlreadyGenerated as error:
        raise ApiError(409, "post_already_generated", str(error)) from error
    except SlotTopicRequired as error:
        raise ApiError(400, "slot_topic_required", str(error)) from error
    except SlotTimeTaken as error:
        raise ApiError(409, "slot_time_taken", str(error)) from error
    except InvalidSlotTransition as error:
        raise ApiError(409, "invalid_transition", str(error)) from error


@router.get("", response_model=list[SlotResponse])
def plan(
    project_id: int,
    container: Container,
    # ``from`` — ключевое слово Python, поэтому имя параметра отличается.
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
):
    return container.api.plan(project_id, date_from=date_from, date_to=date_to)


@router.post("", response_model=SlotResponse, status_code=201)
def create_slot(project_id: int, body: SlotCreateRequest, container: Container):
    return _translated(lambda: container.api.create_slot(project_id, body.model_dump()))


@router.patch("/{slot_id}", response_model=SlotResponse)
def update_slot(
    project_id: int, slot_id: int, body: SlotPatchRequest, container: Container
):
    return _translated(
        lambda: container.api.update_slot(
            project_id, slot_id, body.model_dump(exclude_unset=True)
        )
    )


@router.delete("/{slot_id}", status_code=204)
def delete_slot(project_id: int, slot_id: int, container: Container) -> Response:
    container.api.delete_slot(project_id, slot_id)
    return Response(status_code=204)


@router.post(
    "/{slot_id}/generate", response_model=AcceptedOperationResponse, status_code=202
)
def generate_slot(project_id: int, slot_id: int, container: Container, body: GeneratePostRequest | None = None):
    options = body.model_dump(exclude_defaults=True) if body else {}
    return _translated(lambda: container.api.generate_slot(project_id, slot_id, **options))


@router.post("/{slot_id}/skip", response_model=SlotResponse)
def skip_slot(project_id: int, slot_id: int, container: Container):
    return _translated(lambda: container.api.skip_slot(project_id, slot_id))
