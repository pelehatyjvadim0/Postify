from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from postify.application.ai.gateway import (
    EMBEDDING_DIMENSIONS,
    CallContext,
    CallResult,
    ModelCallError,
    ModelGateway,
)


class FakeProvider:
    """Провайдер с программируемым поведением каждой операции."""

    def __init__(self, name: str = "fake", model: str = "fake-model") -> None:
        self.name = name
        self.model = model
        self.calls: list[tuple[str, object]] = []
        self.text = "ответ"
        self.embedding: tuple[float, ...] = tuple([0.0] * (EMBEDDING_DIMENSIONS - 1) + [1.0])
        self.error: Exception | None = None

    def complete(self, prompt, *, output_schema=None, model=None, reasoning_effort=None):
        self.calls.append(("complete", (prompt, output_schema, model, reasoning_effort)))
        if self.error:
            raise self.error
        return self.text

    def caption_image(self, image_path: Path) -> str:
        self.calls.append(("caption", image_path))
        if self.error:
            raise self.error
        return self.text

    def embed(self, text: str) -> tuple[float, ...]:
        self.calls.append(("embed", text))
        if self.error:
            raise self.error
        return self.embedding


def _gateway(text=None, media=None):
    finished: list[CallResult] = []
    ticks = iter(range(1, 100))
    clock = lambda: datetime(2026, 9, 11, 12, 0, next(ticks), tzinfo=UTC)
    gateway = ModelGateway(
        text or FakeProvider(), media, on_call_finished=finished.append, clock=clock
    )
    return gateway, finished


def test_complete_passes_arguments_and_reports_provider_and_model() -> None:
    provider = FakeProvider("codex", "gpt-x")
    gateway, finished = _gateway(provider)

    result = gateway.complete(
        "напиши",
        context=CallContext("generate", project_id=7, user_id=3),
        output_schema={"type": "object"},
        reasoning_effort="high",
    )

    assert provider.calls == [("complete", ("напиши", {"type": "object"}, None, "high"))]
    assert result.text == "ответ"
    assert result.embedding is None
    assert (result.provider, result.model, result.purpose) == ("codex", "gpt-x", "generate")
    assert result.finished_at > result.started_at
    assert finished == [result]


def test_complete_reports_overridden_model_name() -> None:
    gateway, finished = _gateway(FakeProvider("codex", "default"))

    result = gateway.complete("x", context=CallContext("judge"), model="other")

    assert result.model == "other"
    assert finished[0].model == "other"


def test_caption_and_embed_go_through_media_provider() -> None:
    media = FakeProvider("mock", "mock")
    gateway, finished = _gateway(FakeProvider(), media)

    caption = gateway.caption_image(Path("/tmp/a.png"), context=CallContext("caption"))
    embedding = gateway.embed("подпись", context=CallContext("embedding"))

    assert media.calls == [("caption", Path("/tmp/a.png")), ("embed", "подпись")]
    assert caption.model == "mock" and caption.provider == "mock"
    assert embedding.model == "mock"
    assert embedding.text is None
    assert len(embedding.embedding) == EMBEDDING_DIMENSIONS
    assert len(finished) == 2


def test_hook_fires_exactly_once_on_provider_failure() -> None:
    provider = FakeProvider()
    provider.error = ModelCallError("codex_failed", "упал")
    gateway, finished = _gateway(provider)

    with pytest.raises(ModelCallError) as caught:
        gateway.complete("x", context=CallContext("generate"))

    assert caught.value.code == "codex_failed"
    assert len(finished) == 1
    assert finished[0].text is None and finished[0].embedding is None
    assert finished[0].purpose == "generate"


def test_unexpected_provider_exception_becomes_model_call_error() -> None:
    provider = FakeProvider()
    provider.error = ConnectionResetError("сеть")
    gateway, finished = _gateway(FakeProvider(), provider)

    with pytest.raises(ModelCallError) as caught:
        gateway.embed("x", context=CallContext("embedding"))

    assert caught.value.code == "provider_failed"
    assert len(finished) == 1


def test_embedding_of_wrong_dimension_is_invalid_output() -> None:
    provider = FakeProvider()
    provider.embedding = (1.0, 0.0, 0.0)
    gateway, finished = _gateway(FakeProvider(), provider)

    with pytest.raises(ModelCallError) as caught:
        gateway.embed("x", context=CallContext("embedding"))

    assert caught.value.code == "invalid_output"
    assert len(finished) == 1


def test_empty_text_is_invalid_output() -> None:
    provider = FakeProvider()
    provider.text = "   "
    gateway, finished = _gateway(provider)

    with pytest.raises(ModelCallError) as caught:
        gateway.complete("x", context=CallContext("claims"))

    assert caught.value.code == "invalid_output"
    assert len(finished) == 1


def test_missing_media_provider_is_not_configured() -> None:
    gateway, finished = _gateway(FakeProvider(), None)

    with pytest.raises(ModelCallError) as caught:
        gateway.caption_image(Path("/tmp/a.png"), context=CallContext("vision"))

    assert caught.value.code == "provider_not_configured"
    assert finished == []


def test_failing_hook_does_not_break_the_call() -> None:
    def hook(result: CallResult) -> None:
        raise RuntimeError("учёт сломан")

    gateway = ModelGateway(FakeProvider(), on_call_finished=hook)

    assert gateway.complete("x", context=CallContext("generate")).text == "ответ"


def test_context_rejects_unknown_purpose() -> None:
    with pytest.raises(ValueError):
        CallContext("unknown")
