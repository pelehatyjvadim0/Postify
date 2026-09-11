"""Схемы веб-слоя, разрезанные по доменам контракта API."""

from postify.web.schemas.common import RequestSchema, ResponseSchema
from postify.web.schemas.media import (
    MediaAssetResponse,
    MediaPageResponse,
    MediaPatchRequest,
)
from postify.web.schemas.operations import (
    AcceptedOperationResponse,
    OperationErrorResponse,
    OperationResponse,
    PublicationAttemptResponse,
    PublicationResponse,
)
from postify.web.schemas.plan import (
    SlotCreateRequest,
    SlotPatchRequest,
    SlotPostResponse,
    SlotResponse,
    SlotRubricResponse,
)
from postify.web.schemas.posts import (
    PostDeliveryResponse,
    PostHistoryResponse,
    PostMediaResponse,
    PostPatchRequest,
    PostResponse,
    PostSummaryResponse,
)
from postify.web.schemas.prompts import CommonPromptRequest, CommonPromptResponse
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
    "CommonPromptRequest",
    "CommonPromptResponse",
    "ChannelRequest",
    "ChannelResponse",
    "MediaAssetResponse",
    "MediaPageResponse",
    "MediaPatchRequest",
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
    "SlotCreateRequest",
    "SlotPatchRequest",
    "SlotPostResponse",
    "SlotResponse",
    "SlotRubricResponse",
]
