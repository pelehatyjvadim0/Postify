"""Единый формат ошибки API (раздел 1 контракта).

Тело ответа всегда одно и то же: ``{"error": {"code", "message", "request_id"}}``.
``code`` машиночитаемый и стабильный, ``message`` по-русски и годится для показа
пользователю — поэтому текст берётся либо из словаря ниже, либо из доменного
исключения, которое пишет сообщения для человека.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


# Длинные тексты в UI не помещаются, а из необработанного исключения может
# прилететь что угодно: режем сообщение на границе веб-слоя.
MESSAGE_LIMIT = 300

DEFAULT_MESSAGE = "Не удалось выполнить запрос"

MESSAGES: dict[str, str] = {
    "untrusted_host": "Запрос пришёл с неизвестного хоста",
    "origin_rejected": "Источник запроса не совпадает с адресом приложения",
    "csrf_required": "Не хватает защитного заголовка запроса",
    "authentication_required": "Нужно войти в приложение",
    "not_found": "Объект не найден",
    "validation_error": "Запрос не прошёл проверку",
    "invalid_transition": "Действие недопустимо в текущем состоянии поста",
    "publication_plan_expired": "Время публикации прошло: назначьте новое",
    "operation_busy": "Такая операция уже выполняется",
    "delivery_not_retryable": "Эту отправку нельзя повторить",
    "rubric_in_use": "Рубрику используют слоты контент-плана",
    "post_already_generated": "Пост уже сгенерирован: перегенерируйте или удалите его",
    "slot_topic_required": "Тема слота не заполнена",
    "slot_time_taken": "На это время в плане уже есть слот",
    "channel_delivery_in_flight": "Идёт отправка в канал, отключить его нельзя",
    "publication_channel_unavailable": "Канал проекта не настроен",
    "publication_secret_unavailable": "Токен бота для канала не сохранён",
    "secret_storage_unavailable": "Хранилище секретов не настроено",
    "unsupported_operation": "Операция пока не поддерживается",
    "media_too_large": "Файл слишком велик",
    "provider_rate_limited": "Провайдер временно ограничил запросы",
    "internal_error": "Внутренняя ошибка сервера",
    "http_error": "Запрос отклонён",
    "method_not_allowed": "Метод не поддерживается этим адресом",
    # Коды неудач журнала операций: их UI показывает в карточке операции.
    "media_pool_empty": "Упс, не нашли доступное изображение",
    "generate_post_failed": "Не удалось сгенерировать пост",
    "regenerate_post_failed": "Не удалось перегенерировать пост",
    "publish_once_failed": "Не удалось опубликовать пост",
    "retry_delivery_failed": "Не удалось повторить отправку",
    "derive_rules_failed": "Не удалось разобрать промпт проекта на правила",
    "caption_media_failed": "Не удалось подписать изображение",
}


class ApiError(Exception):
    """Ошибка, которую веб-слой умеет отдать клиенту как есть."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str | None = None,
        *,
        field: str | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field


class NotFoundError(ApiError):
    """Нет объекта либо он принадлежит другому пользователю."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(404, "not_found", message)


class ConflictError(ApiError):
    """Состояние объекта не допускает запрошенного действия."""

    def __init__(self, code: str = "conflict", message: str | None = None) -> None:
        super().__init__(409, code, message)


def message_for(code: str, message: str | None = None) -> str:
    text = message if isinstance(message, str) and message.strip() else None
    if text is None:
        text = MESSAGES.get(code, DEFAULT_MESSAGE)
    return text[:MESSAGE_LIMIT]


def request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else uuid4().hex


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str | None = None,
    *,
    field: str | None = None,
) -> JSONResponse:
    error: dict[str, object] = {
        "code": code,
        "message": message_for(code, message),
        "request_id": request_id(request),
    }
    if field:
        error["field"] = field
    return JSONResponse(status_code=status_code, content={"error": error})
