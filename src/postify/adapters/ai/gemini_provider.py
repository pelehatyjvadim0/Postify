"""Gemini API по HTTP: текст, подпись к изображению и эмбеддинг.

Ключа при написании НЕ БЫЛО, в сеть адаптер не ходил. Имена моделей и
эндпоинты взяты из публичной документации Gemini API и подлежат проверке при
появлении ключа:

- текст и vision: ``POST {BASE_URL}/models/{TEXT_MODEL}:generateContent``;
- эмбеддинг: ``POST {BASE_URL}/models/{EMBEDDING_MODEL}:embedContent`` с полем
  ``outputDimensionality`` — ровно ``EMBEDDING_DIMENSIONS``, иначе вектор не
  ляжет в колонку pgvector и не совпадёт с заглушкой.

Ключ уходит только в заголовке ``x-goog-api-key``: так он не попадает ни в
URL, ни в текст ошибок, ни в журнал. ``reasoning_effort`` не транслируется —
у Gemini другая шкала мышления и её соответствие Codex не подтверждено.
Ретраев нет намеренно: повтор — забота вызывающей операции.
"""

from __future__ import annotations

import base64
import math
import mimetypes
from pathlib import Path

import httpx

from postify.application.ai.gateway import EMBEDDING_DIMENSIONS
from postify.application.ports.model_provider import ModelCallError


BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
TEXT_MODEL = "gemini-3.8-flash"
EMBEDDING_MODEL = "gemini-embedding-001"
# Одинаковый тип задачи для подписи и для поискового запроса: сравнивать надо
# векторы из одного пространства, а не «документ против запроса».
EMBEDDING_TASK_TYPE = "SEMANTIC_SIMILARITY"
# Минимальная инструкция для vision: без неё модели нечего делать с картинкой.
# Это не промпт задачи, а формат ответа; промпты задач живут в треке промптов.
CAPTION_INSTRUCTION = (
    "Опиши изображение одним-двумя предложениями по-русски: что на нём, "
    "какая обстановка и настроение. Без вступлений и без списков."
)


class GeminiModelProvider:
    name = "gemini"

    def __init__(
        self,
        client: httpx.Client,
        *,
        api_key: str,
        model: str = TEXT_MODEL,
        embedding_model: str = EMBEDDING_MODEL,
        base_url: str = BASE_URL,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ModelCallError("provider_not_configured", "GEMINI_API_KEY не задан")
        self._client = client
        self._headers = {"x-goog-api-key": api_key.strip()}
        self.model = model
        self.embedding_model = embedding_model
        self._base = base_url.rstrip("/")

    def complete(
        self,
        prompt: str,
        *,
        output_schema: dict[str, object] | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        body: dict[str, object] = {"contents": [{"parts": [{"text": prompt}]}]}
        if output_schema is not None:
            body["generationConfig"] = {
                "responseMimeType": "application/json",
                "responseSchema": output_schema,
            }
        payload = self._post(f"models/{model or self.model}:generateContent", body)
        return _candidate_text(payload)

    def caption_image(self, image_path: Path) -> str:
        path = Path(image_path)
        try:
            data = path.read_bytes()
        except OSError:
            raise ModelCallError("invalid_output", "Файл изображения недоступен") from None
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = {
            "contents": [
                {
                    "parts": [
                        {"text": CAPTION_INSTRUCTION},
                        {
                            "inline_data": {
                                "mime_type": mime,
                                "data": base64.b64encode(data).decode("ascii"),
                            }
                        },
                    ]
                }
            ]
        }
        payload = self._post(f"models/{self.model}:generateContent", body)
        return _candidate_text(payload)

    def embed(self, text: str) -> tuple[float, ...]:
        body = {
            "content": {"parts": [{"text": text}]},
            "taskType": EMBEDDING_TASK_TYPE,
            "outputDimensionality": EMBEDDING_DIMENSIONS,
        }
        payload = self._post(f"models/{self.embedding_model}:embedContent", body)
        values = payload.get("embedding", {}).get("values") if isinstance(payload, dict) else None
        if not isinstance(values, list) or not all(
            isinstance(value, (int, float)) for value in values
        ):
            raise ModelCallError("invalid_output", "Gemini не вернул вектор")
        # При усечённой размерности Gemini отдаёт ненормированный вектор;
        # нормируем сами, чтобы косинус и L2 в pgvector считались одинаково
        # и совпадали по шкале с заглушкой.
        norm = math.sqrt(sum(float(value) ** 2 for value in values))
        if norm == 0.0:
            raise ModelCallError("invalid_output", "Gemini вернул нулевой вектор")
        return tuple(float(value) / norm for value in values)

    def _post(self, resource: str, body: dict[str, object]) -> dict[str, object]:
        try:
            response = self._client.post(
                f"{self._base}/{resource}", json=body, headers=self._headers
            )
        except httpx.HTTPError as error:
            raise ModelCallError("provider_unavailable", type(error).__name__) from None
        if response.status_code != 200:
            # Тело ответа Google не содержит ключа, но обрезаем на всякий случай.
            raise ModelCallError(
                "provider_unavailable",
                f"HTTP {response.status_code}: {response.text[:200]}",
            )
        try:
            payload = response.json()
        except ValueError:
            raise ModelCallError("invalid_output", "Ответ Gemini не JSON") from None
        if not isinstance(payload, dict):
            raise ModelCallError("invalid_output", "Ответ Gemini не объект")
        return payload


def _candidate_text(payload: dict[str, object]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ModelCallError("invalid_output", "Gemini не вернул кандидатов")
    first = candidates[0]
    content = first.get("content") if isinstance(first, dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise ModelCallError("invalid_output", "Gemini вернул ответ без частей")
    text = "".join(
        part["text"] for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)
    )
    if not text.strip():
        raise ModelCallError("invalid_output", "Gemini вернул пустой текст")
    return text
