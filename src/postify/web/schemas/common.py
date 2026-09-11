"""Базовые классы схем веб-слоя.

Запросы и ответы разведены намеренно: у входа неизвестное поле — ошибка (иначе
опечатка клиента молча теряется), у выхода — allowlist, чтобы внутренние поля
фасада не утекали наружу вместе с ответом.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponseSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")
