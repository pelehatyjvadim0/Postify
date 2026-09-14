"""Данные конвейера генерации поста.

Модель получает строгую JSON-схему: текст, идентификатор изображения из
предложенного шортлиста и краткое обоснование выбора.  Разбор ответа живёт
здесь, чтобы ни HTTP-слой, ни SQL-репозиторий не доверяли произвольному JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from postify.application.ports.validation import DraftMedia, DraftSlot, ValidationReport
from postify.application.prompts.compose_context import PlanSlot


MAX_REPAIR_ITERATIONS = 2

GENERATION_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "post_text": {"type": "string", "minLength": 1},
        "media_asset_id": {"type": "integer", "minimum": 1},
        "media_rationale": {"type": "string", "minLength": 1},
    },
    "required": ["post_text", "media_asset_id", "media_rationale"],
    "additionalProperties": False,
}


TEXT_ONLY_OUTPUT_SCHEMA = {**GENERATION_OUTPUT_SCHEMA, "properties": {**GENERATION_OUTPUT_SCHEMA["properties"], "media_asset_id": {"type": "null"}}}


class GenerationError(RuntimeError):
    """Предсказуемая ошибка конвейера с машинным кодом."""

    def __init__(self, code: str, reason: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.reason = reason


@dataclass(frozen=True, slots=True)
class GenerationBrief:
    """Весь неизменяемый вход одного запуска генерации."""

    project_id: int
    user_id: int
    slot: DraftSlot
    plan: tuple[PlanSlot, ...]
    system_prompt: str
    common_prompt: str
    project_prompt: str
    publication_mode: str
    model: str
    reasoning_effort: str


@dataclass(frozen=True, slots=True)
class GeneratedContent:
    post_text: str
    media_asset_id: int | None
    media_rationale: str

    @classmethod
    def parse(cls, raw: str, *, without_image: bool = False) -> "GeneratedContent":
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise GenerationError(
                "invalid_generation_output", "Модель вернула не JSON"
            ) from error
        if not isinstance(value, dict) or set(value) != {
            "post_text",
            "media_asset_id",
            "media_rationale",
        }:
            raise GenerationError(
                "invalid_generation_output", "Ответ не соответствует JSON-схеме"
            )
        post_text = value["post_text"]
        asset_id = value["media_asset_id"]
        rationale = value["media_rationale"]
        if not isinstance(post_text, str) or not post_text.strip():
            raise GenerationError("invalid_generation_output", "Текст поста пуст")
        if (asset_id is not None if without_image else type(asset_id) is not int or asset_id <= 0):
            raise GenerationError(
                "invalid_generation_output", "Некорректный media_asset_id"
            )
        if not isinstance(rationale, str) or not rationale.strip():
            raise GenerationError(
                "invalid_generation_output", "Обоснование выбора изображения пусто"
            )
        return cls(post_text.strip(), asset_id, rationale.strip())


@dataclass(frozen=True, slots=True)
class GenerationResult:
    post_id: int
    content: GeneratedContent
    media: DraftMedia | None
    validation: ValidationReport
    repair_iterations: int
    provider: str
    model: str
    generated_at: str
    publication_mode: str

    @property
    def validation_passed(self) -> bool:
        return self.validation.passed

    def metadata(self, *, reasoning_effort: str) -> dict[str, Any]:
        """Снимок для ``posts.generation`` и ответа API."""
        return {
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": reasoning_effort,
            "iterations": self.repair_iterations,
            "generated_at": self.generated_at,
            "media_asset_id": self.content.media_asset_id,
            "media_rationale": self.content.media_rationale,
            "validation_passed": self.validation_passed,
            "publication_mode": self.publication_mode,
        }
