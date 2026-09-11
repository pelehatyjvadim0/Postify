"""Схемы общего промпта пользователя — раздел 3 контракта API.

Системного промпта сервера здесь нет и быть не может: он не отдаётся и не
редактируется через API (раздел 13 контракта).
"""

from __future__ import annotations

from pydantic import Field

from postify.web.schemas.common import RequestSchema, ResponseSchema


class CommonPromptRequest(RequestSchema):
    """Замена промпта целиком. Пустая строка — осмысленное значение: сброс."""

    prompt: str = Field(max_length=20_000)


class CommonPromptResponse(ResponseSchema):
    common_prompt: str
