"""Заглушка vision и эмбеддингов на время, пока ключа Gemini нет.

Заглушка НЕ понимает содержимое изображений и НЕ считает смысловую близость.
Подпись собирается из метаданных файла (имя, размер, разрешение из заголовка),
эмбеддинг — из хеша текста. Отключается одной настройкой ``AI_MEDIA_PROVIDER``
(см. ``application.ai.factory``), код при этом не правится.

Всё, что сделала заглушка, помечено ``model == "mock"``: по этому значению трек
пула изображений найдёт и перевыпустит подписи и векторы, когда ключ появится.
"""

from __future__ import annotations

import hashlib
import math
import struct
from pathlib import Path

from postify.application.ai.gateway import EMBEDDING_DIMENSIONS
from postify.application.ports.model_provider import ModelCallError


MODEL_NAME = "mock"


class MockModelProvider:
    """Детерминированная заглушка. Текст не генерирует — это работа Codex."""

    name = "mock"
    model = MODEL_NAME

    def complete(
        self,
        prompt: str,
        *,
        output_schema: dict[str, object] | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        raise ModelCallError("provider_unavailable", "Заглушка не генерирует текст")

    def caption_image(self, image_path: Path) -> str:
        """Подпись из метаданных файла с прямым признанием, что это заглушка.

        Содержимое изображения не анализируется. Разрешение берётся из
        заголовка PNG, JPEG, GIF или WEBP своими силами, без Pillow; если
        формат не распознан — в подписи остаются только имя и размер в байтах.
        """
        path = Path(image_path)
        try:
            size = path.stat().st_size
            with path.open("rb") as stream:
                header = stream.read(65536)
        except OSError:
            raise ModelCallError("invalid_output", "Файл изображения недоступен") from None
        parts = [f"файл {path.name}", f"{size} байт"]
        dimensions = _read_dimensions(header)
        if dimensions is not None:
            parts.append(f"{dimensions[0]}×{dimensions[1]} px")
        else:
            parts.append("разрешение не определено")
        return (
            "Подпись-заглушка (провайдер mock, содержимое изображения не "
            "анализировалось): " + ", ".join(parts) + "."
        )

    def embed(self, text: str) -> tuple[float, ...]:
        """Детерминированный вектор длины ``EMBEDDING_DIMENSIONS`` из хеша текста.

        Одинаковый текст всегда даёт одинаковый вектор, разные тексты — разные.
        Вектор нормирован до единичной длины. Но это НЕ семантический эмбеддинг:
        близкие по словам тексты не обязаны быть близкими по вектору, поиск по
        таким векторам — не рабочий поиск, а проверка сантехники. Не принимать
        результаты подбора изображений на заглушке за осмысленные.
        """
        needed = EMBEDDING_DIMENSIONS * 2
        digest = b""
        counter = 0
        payload = text.encode("utf-8")
        while len(digest) < needed:
            digest += hashlib.sha256(counter.to_bytes(4, "big") + payload).digest()
            counter += 1
        raw = struct.unpack(f">{EMBEDDING_DIMENSIONS}H", digest[:needed])
        values = [value / 65535.0 * 2.0 - 1.0 for value in raw]
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0.0:
            # Практически недостижимо для sha256, но деление на ноль хуже.
            values[0] = 1.0
            norm = 1.0
        return tuple(value / norm for value in values)


def _read_dimensions(header: bytes) -> tuple[int, int] | None:
    """Ширина и высота из заголовка файла; ``None``, если формат не распознан."""
    try:
        if header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR":
            return struct.unpack(">II", header[16:24])
        if header[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", header[6:10])
        if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
            return _webp_dimensions(header)
        if header[:2] == b"\xff\xd8":
            return _jpeg_dimensions(header)
    except (struct.error, IndexError):
        return None
    return None


def _webp_dimensions(header: bytes) -> tuple[int, int] | None:
    chunk = header[12:16]
    if chunk == b"VP8X":
        width = int.from_bytes(header[24:27], "little") + 1
        height = int.from_bytes(header[27:30], "little") + 1
        return width, height
    if chunk == b"VP8 ":
        width, height = struct.unpack("<HH", header[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L":
        bits = int.from_bytes(header[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def _jpeg_dimensions(header: bytes) -> tuple[int, int] | None:
    # Идём по сегментам до первого SOFn: там лежат высота и ширина кадра.
    offset = 2
    while offset + 9 <= len(header):
        if header[offset] != 0xFF:
            return None
        marker = header[offset + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        length = struct.unpack(">H", header[offset + 2 : offset + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", header[offset + 5 : offset + 9])
            return width, height
        offset += 2 + length
    return None
