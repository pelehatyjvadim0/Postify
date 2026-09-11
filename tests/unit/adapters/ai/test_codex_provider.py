from __future__ import annotations

from pathlib import Path

import pytest

from postify.adapters.ai.codex_cli import CodexCallError
from postify.adapters.ai.codex_provider import CodexModelProvider
from postify.application.ai.gateway import ModelCallError


class FakeCli:
    def __init__(self, model: str = "gpt-5.6-terra", error: Exception | None = None) -> None:
        self.model = model
        self.error = error
        self.calls: list[tuple] = []

    def complete(self, prompt, *, output_schema=None, model=None, reasoning_effort=None):
        self.calls.append((prompt, output_schema, model, reasoning_effort))
        if self.error:
            raise self.error
        return "текст модели"


def test_complete_delegates_to_cli() -> None:
    cli = FakeCli()
    provider = CodexModelProvider(cli)

    result = provider.complete(
        "запрос", output_schema={"type": "object"}, model="other", reasoning_effort="high"
    )

    assert result == "текст модели"
    assert cli.calls == [("запрос", {"type": "object"}, "other", "high")]
    assert provider.model == "gpt-5.6-terra"
    assert provider.name == "codex"


def test_codex_failure_becomes_model_call_error() -> None:
    provider = CodexModelProvider(FakeCli(error=CodexCallError("codex_failed", "stderr")))

    with pytest.raises(ModelCallError) as caught:
        provider.complete("запрос")

    assert caught.value.code == "codex_failed"
    assert caught.value.reason == "stderr"


def test_codex_cannot_do_vision_or_embeddings() -> None:
    provider = CodexModelProvider(FakeCli())

    for call in (
        lambda: provider.caption_image(Path("/tmp/a.png")),
        lambda: provider.embed("текст"),
    ):
        with pytest.raises(ModelCallError) as caught:
            call()
        assert caught.value.code == "provider_unavailable"
