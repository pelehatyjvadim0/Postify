from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, create_model


def _strict_boolean(value: object) -> object:
    if type(value) is not bool:
        raise ValueError("selected должен быть boolean")
    return value


StrictTrue = Annotated[Literal[True], BeforeValidator(_strict_boolean)]
StrictFalse = Annotated[Literal[False], BeforeValidator(_strict_boolean)]


class _TopicOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    attempt_id: int = Field(gt=0)
    analysis: str = Field(min_length=1)
    usefulness: int = Field(ge=0, le=100)


class SelectedTopicOutput(_TopicOutput):
    selected: StrictTrue
    post_text: str = Field(min_length=1)
    media_query: str = Field(min_length=1)


class UnselectedTopicOutput(_TopicOutput):
    selected: StrictFalse
    post_text: None
    media_query: None


TopicOutput = SelectedTopicOutput | UnselectedTopicOutput


def batch_output_model(article_count: int) -> type[BaseModel]:
    if article_count <= 0:
        raise ValueError("article_count должен быть положительным")
    topics = Annotated[
        list[TopicOutput],
        Field(min_length=article_count, max_length=article_count),
    ]
    return create_model(
        "CodexBatchOutput",
        __config__=ConfigDict(extra="forbid", strict=True),
        topics=(topics, ...),
    )


def batch_output_schema(article_count: int) -> dict[str, object]:
    schema = batch_output_model(article_count).model_json_schema()
    definitions = schema.pop("$defs", {})

    def inline(value: object) -> object:
        if isinstance(value, list):
            return [inline(item) for item in value]
        if not isinstance(value, dict):
            return value
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            name = reference.rsplit("/", 1)[-1]
            resolved = deepcopy(definitions[name])
            resolved.update({key: item for key, item in value.items() if key != "$ref"})
            return inline(resolved)
        return {key: inline(item) for key, item in value.items()}

    return inline(schema)  # type: ignore[return-value]
