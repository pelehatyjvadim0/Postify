from __future__ import annotations

import struct
from pathlib import Path

import pytest

from postify.adapters.ai.mock_provider import MockModelProvider
from postify.application.ai.gateway import EMBEDDING_DIMENSIONS, ModelCallError


def _png(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
    )


def _jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof0 = (
        b"\xff\xc0"
        + struct.pack(">H", 17)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03" + b"\x00" * 9
    )
    return b"\xff\xd8" + app0 + sof0


def _gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * 4


def _webp(width: int, height: int) -> bytes:
    return (
        b"RIFF"
        + struct.pack("<I", 30)
        + b"WEBP"
        + b"VP8X"
        + struct.pack("<I", 10)
        + b"\x00" * 4
        + (width - 1).to_bytes(3, "little")
        + (height - 1).to_bytes(3, "little")
    )


def test_model_name_is_honestly_mock() -> None:
    assert MockModelProvider().model == "mock"
    assert MockModelProvider().name == "mock"


@pytest.mark.parametrize(
    "builder", [_png, _jpeg, _gif, _webp], ids=["png", "jpeg", "gif", "webp"]
)
def test_caption_reports_name_size_and_resolution(tmp_path: Path, builder) -> None:
    image = tmp_path / "снимок.img"
    payload = builder(640, 480)
    image.write_bytes(payload)

    caption = MockModelProvider().caption_image(image)

    assert "снимок.img" in caption
    assert f"{len(payload)} байт" in caption
    assert "640×480 px" in caption
    assert "mock" in caption and "не анализировалось" in caption


def test_caption_admits_unknown_resolution(tmp_path: Path) -> None:
    image = tmp_path / "неизвестный.bin"
    image.write_bytes(b"\x00" * 64)

    caption = MockModelProvider().caption_image(image)

    assert "разрешение не определено" in caption


def test_caption_of_missing_file_is_invalid_output(tmp_path: Path) -> None:
    with pytest.raises(ModelCallError) as caught:
        MockModelProvider().caption_image(tmp_path / "нет.png")

    assert caught.value.code == "invalid_output"


def test_embedding_has_fixed_dimension_and_unit_length() -> None:
    vector = MockModelProvider().embed("рассвет над рекой")

    assert len(vector) == EMBEDDING_DIMENSIONS
    assert all(isinstance(value, float) for value in vector)
    assert abs(sum(value * value for value in vector) - 1.0) < 1e-9


def test_embedding_is_deterministic_and_distinguishes_texts() -> None:
    provider = MockModelProvider()

    assert provider.embed("один и тот же") == provider.embed("один и тот же")
    assert provider.embed("первый") != provider.embed("второй")
    assert MockModelProvider().embed("текст") == provider.embed("текст")


def test_embedding_of_empty_text_is_still_valid() -> None:
    assert len(MockModelProvider().embed("")) == EMBEDDING_DIMENSIONS


def test_mock_does_not_pretend_to_generate_text() -> None:
    with pytest.raises(ModelCallError) as caught:
        MockModelProvider().complete("напиши пост")

    assert caught.value.code == "provider_unavailable"
