"""ORM-модели, разнесённые по доменам.

Пакет собирает единую ``Base`` и реэкспортирует модели, чтобы треки могли
править свои таблицы, не встречаясь в одном файле.
"""

from postify.infrastructure.database.models.base import Base
from postify.infrastructure.database.models.delivery import (
    DeliveryAttemptModel,
    DeliveryModel,
)
from postify.infrastructure.database.models.media import MediaAssetModel, MediaUsageModel
from postify.infrastructure.database.models.observability import OperationRunModel
from postify.infrastructure.database.models.plan import ContentPlanSlotModel
from postify.infrastructure.database.models.posts import (
    PostModel,
    PostStatusHistoryModel,
)
from postify.infrastructure.database.models.prompts import AppSettingsModel
from postify.infrastructure.database.models.projects import (
    ChannelConnectionModel,
    ContentProjectModel,
    ProjectRubricModel,
)
from postify.infrastructure.database.models.scheduling import (
    ScheduledJobModel,
    ScheduleSlotClaimModel,
)
from postify.infrastructure.database.models.users import (
    LoginRequestModel,
    UserModel,
    UserSessionModel,
    UserSettingsModel,
)
from postify.infrastructure.database.models.validation import (
    ProjectRuleModel,
    ValidationReportModel,
)


__all__ = [
    "AppSettingsModel",
    "Base",
    "ChannelConnectionModel",
    "ContentPlanSlotModel",
    "ContentProjectModel",
    "DeliveryAttemptModel",
    "DeliveryModel",
    "LoginRequestModel",
    "MediaAssetModel",
    "MediaUsageModel",
    "OperationRunModel",
    "PostModel",
    "PostStatusHistoryModel",
    "ProjectRubricModel",
    "ScheduleSlotClaimModel",
    "ScheduledJobModel",
    "UserModel",
    "UserSessionModel",
    "UserSettingsModel",
    "ProjectRuleModel",
    "ValidationReportModel",
]
