from __future__ import annotations

from typing import Literal
from pydantic import Field
from postify.web.schemas.common import RequestSchema, ResponseSchema

class RuleRequest(RequestSchema):
    text: str = Field(min_length=1)
    severity: Literal["block", "warn"] = "block"
    enabled: bool = True
    origin: Literal["manual", "derived"] = "manual"

class RuleResponse(ResponseSchema):
    id: int
    text: str
    severity: str
    enabled: bool
    origin: str
    position: int

class RulesRequest(RequestSchema):
    rules: list[RuleRequest]

class RulesResponse(ResponseSchema):
    rules: tuple[RuleResponse, ...]
