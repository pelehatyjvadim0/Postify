"""Общий промпт пользователя — раздел 3 контракта API.

Единственный эндпоинт: ``PUT /api/me/prompt``. Читается промпт вместе с
профилем в ``GET /api/me``, поэтому отдельного ``GET`` здесь нет.

Системного промпта сервера в этом роутере нет намеренно (раздел 13 контракта):
его не отдаёт ни один маршрут, правится он только через CLI или базу.

Маршрут без ``project_id``: владелец промпта — сам вошедший пользователь,
поэтому проверка владения проектом здесь неприменима, а ``current_user``
обязателен.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from postify.domain.auth.models import User
from postify.web.auth import current_user
from postify.web.schemas.prompts import CommonPromptRequest, CommonPromptResponse


CurrentUser = Annotated[User, Depends(current_user)]

router = APIRouter(prefix="/api/me", tags=["prompts"])


def prompt_repository(request: Request):
    """Хранилище промптов из состояния приложения.

    Как и сервис входа, репозиторий строится лениво из настроек, если сборка
    его не положила: так роутер не зависит от общего фасада, а тесты
    подставляют в ``app.state.prompts`` свою реализацию.
    """
    repository = getattr(request.app.state, "prompts", None)
    if repository is None:
        repository = _repository_from_settings()
        request.app.state.prompts = repository
    return repository


PromptRepository = Annotated[object, Depends(prompt_repository)]


@router.put("/prompt", response_model=CommonPromptResponse)
def set_common_prompt(
    body: CommonPromptRequest, user: CurrentUser, repository: PromptRepository
):
    """Заменяет общий промпт пользователя целиком."""
    saved = repository.set_common_prompt(
        user.id, body.prompt.strip(), now=datetime.now(UTC)
    )
    return {"common_prompt": saved}


def _repository_from_settings():
    from sqlalchemy.orm import sessionmaker

    from postify.config import Settings
    from postify.infrastructure.database.engine import create_engine_from_settings
    from postify.infrastructure.repositories.sqlalchemy_prompts import (
        SqlAlchemyPromptRepository,
    )

    engine = create_engine_from_settings(Settings())
    return SqlAlchemyPromptRepository(sessionmaker(engine, expire_on_commit=False))
