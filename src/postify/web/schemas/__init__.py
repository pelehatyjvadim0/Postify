"""Схемы веб-слоя, разрезанные по доменам контракта API."""

from postify.web.schemas.common import RequestSchema, ResponseSchema
from postify.web.schemas.operations import (
    AcceptedOperationResponse,
    OperationErrorResponse,
    OperationResponse,
    PublicationAttemptResponse,
    PublicationResponse,
)
from postify.web.schemas.posts import (
    PostDeliveryResponse,
    PostHistoryResponse,
    PostMediaResponse,
    PostPatchRequest,
    PostResponse,
    PostSummaryResponse,
)
from postify.web.schemas.projects import (
    ChannelRequest,
    ChannelResponse,
    ProjectCreateRequest,
    ProjectMediaResponse,
    ProjectResponse,
    ProjectSummaryResponse,
    ProjectUpdateRequest,
    RubricCreateRequest,
    RubricResponse,
    RubricUpdateRequest,
)


__all__ = [
    "AcceptedOperationResponse",
    "ChannelRequest",
    "ChannelResponse",
    "OperationErrorResponse",
    "OperationResponse",
    "PostDeliveryResponse",
    "PostHistoryResponse",
    "PostMediaResponse",
    "PostPatchRequest",
    "PostResponse",
    "PostSummaryResponse",
    "ProjectCreateRequest",
    "ProjectMediaResponse",
    "ProjectResponse",
    "ProjectSummaryResponse",
    "ProjectUpdateRequest",
    "PublicationAttemptResponse",
    "PublicationResponse",
    "RequestSchema",
    "ResponseSchema",
    "RubricCreateRequest",
    "RubricResponse",
    "RubricUpdateRequest",
]
