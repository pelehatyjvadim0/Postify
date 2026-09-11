"""Граница веб-слоя: контейнер с фасадом приложения и его протокол.

Роутеры не знают ничего, кроме этого протокола, поэтому тесты подставляют в
контейнер заглушку вместо настоящего фасада с базой.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Protocol

from fastapi import Depends, Request


class WebApi(Protocol):
    """Действия и выборки, которыми пользуется HTTP-слой."""

    def scheduler_tick(self) -> object: ...

    def close(self) -> None: ...

    # --- проекты ----------------------------------------------------------

    def list_projects(self, *, owner_id: int) -> list[dict[str, Any]]: ...

    def create_project(
        self, payload: dict[str, object], *, owner_id: int
    ) -> dict[str, Any]: ...

    def project(self, project_id: int) -> dict[str, Any]: ...

    def update_project(
        self, project_id: int, payload: dict[str, object]
    ) -> dict[str, Any]: ...

    def delete_project(self, project_id: int) -> None: ...

    # --- канал ------------------------------------------------------------

    def set_channel(
        self, project_id: int, *, bot_token: str | None = None, chat_id: str
    ) -> dict[str, Any]: ...

    def check_channel(self, project_id: int) -> dict[str, Any]: ...

    def remove_channel(self, project_id: int) -> None: ...

    # --- рубрики ----------------------------------------------------------

    def rubrics(self, project_id: int) -> list[dict[str, Any]]: ...

    def create_rubric(
        self, project_id: int, payload: dict[str, object]
    ) -> dict[str, Any]: ...

    def update_rubric(
        self, project_id: int, rubric_id: int, payload: dict[str, object]
    ) -> dict[str, Any]: ...

    def delete_rubric(self, project_id: int, rubric_id: int) -> None: ...

    # --- контент-план -----------------------------------------------------

    def plan(
        self, project_id: int, *, date_from: date, date_to: date
    ) -> list[dict[str, Any]]: ...

    def create_slot(
        self, project_id: int, payload: dict[str, object]
    ) -> dict[str, Any]: ...

    def update_slot(
        self, project_id: int, slot_id: int, payload: dict[str, object]
    ) -> dict[str, Any]: ...

    def delete_slot(self, project_id: int, slot_id: int) -> None: ...

    def generate_slot(self, project_id: int, slot_id: int) -> dict[str, Any]: ...

    def skip_slot(self, project_id: int, slot_id: int) -> dict[str, Any]: ...

    # --- посты ------------------------------------------------------------

    def posts(
        self,
        project_id: int,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...

    def post(self, project_id: int, post_id: int) -> dict[str, Any]: ...

    def update_post(
        self,
        project_id: int,
        post_id: int,
        *,
        post_text: str | None = None,
        media_asset_id: int | None = None,
    ) -> dict[str, Any]: ...

    def approve_post(self, project_id: int, post_id: int) -> dict[str, Any]: ...

    def reject_post(self, project_id: int, post_id: int) -> dict[str, Any]: ...

    def regenerate_post(self, project_id: int, post_id: int) -> dict[str, Any]: ...

    def rules(self, project_id: int) -> object: ...
    def replace_rules(self, project_id: int, rules: object) -> object: ...
    def derive_rules(self, project_id: int) -> dict[str, Any]: ...

    def post_media(self, project_id: int, post_id: int) -> tuple[bytes, str]: ...

    # --- журнал и публикации ---------------------------------------------

    def operations(
        self, project_id: int, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]: ...

    def operation(self, project_id: int, operation_id: int) -> dict[str, Any]: ...

    def publications(
        self, project_id: int, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]: ...

    def retry_delivery(self, project_id: int, delivery_id: int) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class WebContainer:
    """Явная граница веба: тесты подставляют сюда полный фасад приложения."""

    api: WebApi


def build_default_container() -> WebContainer:
    from postify.web.services import build_web_api

    return WebContainer(api=build_web_api())


def container_for(request: Request) -> WebContainer:
    return request.app.state.container


Container = Annotated[WebContainer, Depends(container_for)]
