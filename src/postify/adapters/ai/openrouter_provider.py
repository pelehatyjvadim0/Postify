"""OpenRouter по HTTP: текст, подпись к изображению и эмбеддинг.

OpenRouter совместим с OpenAI: текст и vision идут одним эндпоинтом
``POST {BASE_URL}/chat/completions``, эмбеддинги — отдельным
``POST {BASE_URL}/embeddings``. Поэтому один провайдер закрывает все три
операции протокола, и второй HTTP-клиент не нужен.

Все три пути проверены живыми запросами с ключом (сентябрь 2026): верхнеуровневое
``dimensions`` в ``/embeddings`` принимается и даёт ровно ``EMBEDDING_DIMENSIONS``
чисел, картинка data-URL в ``image_url`` понимается, ``response_format`` со схемой
соблюдается. Вектор при этом приходил уже почти нормированным (норма 1.0003), но
нормировка ниже остаётся: она дешёвая и страхует от модели, которая отдаст
ненормированный вектор.

Ключ уходит только заголовком ``Authorization: Bearer``: так он не попадает ни
в URL, ни в текст ошибок, ни в журнал. Ретраев нет намеренно: повтор — забота
вызывающей операции.

``reasoning_effort`` транслируется в унифицированное поле ``reasoning.effort``,
а не в openai-совместимый ``reasoning_effort``: второй объявляют не все модели
(например, у Anthropic его в списке параметров нет), первый OpenRouter понимает
для всех и сам отображает уровень на ближайший поддерживаемый. Значение вне
шкалы OpenRouter не отправляется вовсе — лучше вызов без управления мышлением,
чем HTTP 400. Модели без рассуждений поле игнорируют.
"""

from __future__ import annotations

import base64
import math
import mimetypes
from pathlib import Path

import httpx

from postify.application.ai.gateway import EMBEDDING_DIMENSIONS
from postify.application.ports.model_provider import ModelCallError


BASE_URL = "https://openrouter.ai/api/v1"
# Одна мультимодальная модель на текст и vision: в настройках один
# OPENROUTER_MODEL, значит модель обязана уметь и картинку, и структурированный
# вывод. Нужна она прежде всего для подписей к изображениям — основной
# генератор текста остаётся Codex, — поэтому взят дешёвый и быстрый тариф с
# большим контекстом: проверено, что по-русски отвечает.
TEXT_MODEL = "google/gemini-3.1-flash-lite"
# Усечение размерности до 768 подтверждено живым запросом; 768 держит колонка
# pgvector пула изображений.
EMBEDDING_MODEL = "openai/text-embedding-3-small"
# Шкала OpenRouter для reasoning.effort; включает всю шкалу
# CONTENT_REASONING_EFFORT. Уровня "none" здесь намеренно нет: модели с
# обязательными рассуждениями отвечают на него ошибкой.
REASONING_EFFORTS = frozenset({"minimal", "low", "medium", "high", "xhigh", "max"})
# Минимальная инструкция для vision: без неё модели нечего делать с картинкой.
# Это не промпт задачи, а формат ответа; промпты задач живут в треке промптов.
# Подпись уходит в эмбеддинг и в поиск, поэтому нужны объекты и обстановка,
# а не впечатления: оценки и настроение размывают вектор и портят подбор.
CAPTION_INSTRUCTION = (
    "Перечисли по-русски, что изображено: объекты, обстановка, план, время "
    "суток, если оно понятно. Одно предложение, не длиннее 25 слов. Без "
    "вступлений, списков, оценок и слов о настроении. Если объект непонятен, "
    "назови его форму и цвет."
)


class OpenRouterModelProvider:
    name = "openrouter"

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
            raise ModelCallError(
                "provider_not_configured", "OPENROUTER_API_KEY не задан"
            )
        self._client = client
        # Одного Authorization достаточно: HTTP-Referer и X-Title необязательны.
        self._headers = {"Authorization": f"Bearer {api_key.strip()}"}
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
        body: dict[str, object] = {
            "model": model or self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if output_schema is not None:
            # strict=true заставляет провайдера соблюдать схему, а не «стараться».
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "output",
                    "strict": True,
                    "schema": output_schema,
                },
            }
        if reasoning_effort in REASONING_EFFORTS:
            body["reasoning"] = {"effort": reasoning_effort}
        return _message_text(self._post("chat/completions", body))

    def caption_image(self, image_path: Path) -> str:
        """Подпись к изображению: картинка уходит data-URL внутри ``image_url``.

        Отдельного хранилища у OpenRouter нет, ссылки на файл в интернете у нас
        тоже нет — значит байты идут прямо в теле запроса.
        """
        path = Path(image_path)
        try:
            data = path.read_bytes()
        except OSError:
            raise ModelCallError("invalid_output", "Файл изображения недоступен") from None
        # Тип берём по расширению: содержимое файла проверяет пул при загрузке.
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(data).decode("ascii")
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": CAPTION_INSTRUCTION},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{encoded}"},
                        },
                    ],
                }
            ],
        }
        return _message_text(self._post("chat/completions", body))

    def embed(self, text: str) -> tuple[float, ...]:
        body = {
            "model": self.embedding_model,
            "input": text,
            "encoding_format": "float",
            "dimensions": EMBEDDING_DIMENSIONS,
        }
        payload = self._post("embeddings", body)
        data = payload.get("data")
        first = data[0] if isinstance(data, list) and data else None
        values = first.get("embedding") if isinstance(first, dict) else None
        if not isinstance(values, list) or not all(
            isinstance(value, (int, float)) for value in values
        ):
            raise ModelCallError("invalid_output", "OpenRouter не вернул вектор")
        # При усечённой размерности вектор нередко приходит ненормированным;
        # нормируем сами, чтобы косинус и L2 в pgvector считались одинаково
        # и совпадали по шкале с заглушкой.
        norm = math.sqrt(sum(float(value) ** 2 for value in values))
        if norm == 0.0:
            raise ModelCallError("invalid_output", "OpenRouter вернул нулевой вектор")
        return tuple(float(value) / norm for value in values)

    def _post(self, resource: str, body: dict[str, object]) -> dict[str, object]:
        try:
            response = self._client.post(
                f"{self._base}/{resource}", json=body, headers=self._headers
            )
        except httpx.HTTPError as error:
            raise ModelCallError("provider_unavailable", type(error).__name__) from None
        if response.status_code != 200:
            # Ключа в ответе нет, но тело всё равно обрезаем: оно может быть любым.
            raise ModelCallError(
                "provider_unavailable",
                f"HTTP {response.status_code}: {response.text[:200]}",
            )
        try:
            payload = response.json()
        except ValueError:
            raise ModelCallError("invalid_output", "Ответ OpenRouter не JSON") from None
        if not isinstance(payload, dict):
            raise ModelCallError("invalid_output", "Ответ OpenRouter не объект")
        return payload


def _message_text(payload: dict[str, object]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        # Причина отказа лежит в поле error, иногда рядом с кодом 200.
        raise ModelCallError(
            "invalid_output", _error_hint(payload) or "OpenRouter не вернул ответ"
        )
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise ModelCallError("invalid_output", "OpenRouter вернул пустой текст")
    return text


def _error_hint(payload: dict[str, object]) -> str:
    error = payload.get("error")
    return str(error)[:200] if error else ""
