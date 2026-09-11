from __future__ import annotations

import json

from postify.application.ai.gateway import CallContext, ModelGateway
from postify.application.ports.model_provider import ModelCallError
from .models import ProjectRule

DERIVE_RULES_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"rules": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "severity": {"type": "string", "enum": ["block", "warn"]},
        },
        "required": ["text", "severity"],
        "additionalProperties": False,
    }}},
    "required": ["rules"],
    "additionalProperties": False,
}


def derive_rules(gateway: ModelGateway, *, project_id: int, project_prompt: str, user_id: int | None = None) -> tuple[ProjectRule, ...]:
    prompt = "Разбери промпт проекта на проверяемые правила для постов. Верни JSON {rules:[{text:string,severity:'block'|'warn'}]}. Ничего не сохраняй.\n" + project_prompt
    result = gateway.complete(prompt, context=CallContext("derive_rules", project_id=project_id, user_id=user_id), output_schema=DERIVE_RULES_OUTPUT_SCHEMA)
    try:
        data = json.loads(result.text or "{}")
    except json.JSONDecodeError as error:
        raise ModelCallError("invalid_output", "Модель вернула некорректный список правил") from error
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise ModelCallError("invalid_output", "Модель не вернула список правил")
    return tuple(ProjectRule(0, project_id, str(item["text"]).strip(), item.get("severity", "block"), True, "derived", i) for i, item in enumerate(data.get("rules", [])) if isinstance(item, dict) and str(item.get("text", "")).strip() and item.get("severity", "block") in {"block", "warn"})
