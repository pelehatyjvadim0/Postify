"""Бот входа: HTTP-адаптер Telegram Bot API и цикл опроса.

Токен и жизненный цикл у него собственные, с доставкой постов в каналы он не
пересекается. ``getUpdates`` на одном токене допускает ровно один опрашивающий
процесс, поэтому цикл поднимается один раз в жизненном цикле приложения;
вебхук на этом токене не используется.

Ошибки Telegram логируются и не валят процесс: как в образце — пауза и повтор.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import re
from typing import Any

import httpx

from postify.domain.auth.models import (
    AuthError,
    LoginRequestExpired,
    TelegramIdentity,
    display_name_of,
)


LOGGER = logging.getLogger(__name__)

# Токен в диплинке ровно 43 символа base64url — как выдаёт token_urlsafe(32).
START_PATTERN = re.compile(r"^/start(?:@[A-Za-z0-9_]+)?\s+login_([A-Za-z0-9_-]{43})$")
CALLBACK_PATTERN = re.compile(r"^login_(yes|no)_([A-Za-z0-9_-]{43})$")

CONFIRM_TEXT = (
    "Подтвердите вход\n\n"
    "Кто-то пытается войти в AutoPostTG через ваш Telegram-аккаунт. Это вы?"
)
EXPIRED_TEXT = "Запрос на вход истёк. Вернитесь на сайт и начните вход заново."
STALE_TEXT = "Запрос на вход уже недействителен"
FOREIGN_TEXT = "Этот запрос создан для другого пользователя"
APPROVED_TEXT = "Вход подтверждён. Вернитесь в браузер."
DENIED_TEXT = (
    "Вход отклонён. Если это были не вы, никаких дополнительных действий не требуется."
)
YES_BUTTON = "Это я"
NO_BUTTON = "Это не я"


class TelegramAuthError(RuntimeError):
    """Telegram отказал или недоступен."""


class TelegramAuthBot:
    """Минимальный клиент Bot API для входа."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        bot_token: str,
        api_base: str = "https://api.telegram.org",
    ) -> None:
        self._client = client
        # Токен попадает только в URL запроса и никогда в журнал.
        self._base = f"{api_base.rstrip('/')}/bot{bot_token}"

    async def _call(self, method: str, payload: dict[str, Any], *, timeout: float) -> Any:
        try:
            response = await self._client.post(
                f"{self._base}/{method}", json=payload, timeout=timeout
            )
        except httpx.HTTPError as error:
            raise TelegramAuthError(f"{method}: транспорт недоступен") from error
        try:
            body = response.json()
        except ValueError as error:
            raise TelegramAuthError(f"{method}: некорректный ответ") from error
        if not isinstance(body, dict) or body.get("ok") is not True:
            description = body.get("description") if isinstance(body, dict) else None
            raise TelegramAuthError(f"{method}: {description or response.status_code}")
        return body.get("result")

    async def get_me(self) -> dict[str, Any]:
        result = await self._call("getMe", {}, timeout=15.0)
        return result if isinstance(result, dict) else {}

    async def get_updates(self, *, offset: int, timeout: int = 25) -> list[dict[str, Any]]:
        result = await self._call(
            "getUpdates",
            {
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": ["message", "callback_query"],
            },
            # Запас поверх long polling, иначе клиент рвёт живой запрос.
            timeout=timeout + 10.0,
        )
        return [item for item in result or [] if isinstance(item, dict)]

    async def send_message(
        self, *, chat_id: Any, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        result = await self._call("sendMessage", payload, timeout=15.0)
        return result if isinstance(result, dict) else {}

    async def answer_callback_query(
        self, *, callback_query_id: str, text: str | None = None, show_alert: bool = False
    ) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text is not None:
            payload["text"] = text
            payload["show_alert"] = show_alert
        await self._call("answerCallbackQuery", payload, timeout=15.0)

    async def edit_message_text(
        self, *, chat_id: Any, message_id: int, text: str
    ) -> None:
        await self._call(
            "editMessageText",
            {"chat_id": chat_id, "message_id": message_id, "text": text},
            timeout=15.0,
        )


def confirmation_keyboard(telegram_token: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": YES_BUTTON, "callback_data": f"login_yes_{telegram_token}"}],
            [{"text": NO_BUTTON, "callback_data": f"login_no_{telegram_token}"}],
        ]
    }


class AuthBotPoller:
    """Цикл getUpdates, дёргающий действия входа.

    Действия синхронные (репозиторий на SQLAlchemy), поэтому вызываются через
    ``asyncio.to_thread``: цикл не блокирует event loop.
    """

    def __init__(
        self,
        bot: TelegramAuthBot,
        service,
        *,
        poll_timeout: int = 25,
        retry_delay: float = 3.0,
        to_thread: Callable[..., Any] = asyncio.to_thread,
    ) -> None:
        self._bot = bot
        self._service = service
        self._poll_timeout = poll_timeout
        self._retry_delay = retry_delay
        self._to_thread = to_thread
        self._offset = 0

    async def resolve_username(self) -> str:
        """Имя бота: из настройки, а при её отсутствии — из getMe."""
        try:
            return self._service.bot_username()
        except AuthError:
            pass
        profile = await self._bot.get_me()
        username = profile.get("username")
        self._service.set_bot_username(username if isinstance(username, str) else None)
        return self._service.bot_username()

    async def run(self) -> None:
        """Опрашивает Telegram до отмены задачи. Ошибки не валят процесс."""
        while True:
            try:
                await self.resolve_username()
                while True:
                    updates = await self._bot.get_updates(
                        offset=self._offset, timeout=self._poll_timeout
                    )
                    for update in updates:
                        update_id = update.get("update_id")
                        if isinstance(update_id, int):
                            self._offset = max(self._offset, update_id + 1)
                        await self.handle(update)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # цикл входа обязан пережить сбой Telegram
                LOGGER.warning("Опрос бота входа: %s", error)
                await asyncio.sleep(self._retry_delay)

    async def handle(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if isinstance(message, dict):
            await self._handle_start(message)
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            await self._handle_decision(callback)

    async def _handle_start(self, message: dict[str, Any]) -> None:
        match = START_PATTERN.match(str(message.get("text") or ""))
        sender = message.get("from")
        chat = message.get("chat")
        if not match or not isinstance(sender, dict) or not isinstance(chat, dict):
            return
        telegram_token = match.group(1)
        identity = _identity(sender)
        try:
            await self._to_thread(
                self._service.handle_bot_start,
                telegram_token=telegram_token,
                identity=identity,
            )
        except LoginRequestExpired:
            await self._bot.send_message(chat_id=chat.get("id"), text=EXPIRED_TEXT)
            return
        await self._bot.send_message(
            chat_id=chat.get("id"),
            text=CONFIRM_TEXT,
            reply_markup=confirmation_keyboard(telegram_token),
        )

    async def _handle_decision(self, callback: dict[str, Any]) -> None:
        match = CALLBACK_PATTERN.match(str(callback.get("data") or ""))
        sender = callback.get("from")
        callback_id = callback.get("id")
        if not match or not isinstance(sender, dict) or not isinstance(callback_id, str):
            return
        approved = match.group(1) == "yes"
        telegram_token = match.group(2)
        telegram_user_id = str(sender.get("id"))
        request = await self._to_thread(
            self._service.repository.login_request_by_telegram_token, telegram_token
        )
        # Чужое нажатие отклоняется до записи решения: подтвердить может только
        # тот аккаунт, который прислал /start.
        if request is not None and request.telegram_user_id not in (None, telegram_user_id):
            await self._bot.answer_callback_query(
                callback_query_id=callback_id, text=FOREIGN_TEXT, show_alert=True
            )
            return
        try:
            await self._to_thread(
                self._service.handle_bot_decision,
                telegram_token=telegram_token,
                telegram_user_id=telegram_user_id,
                approved=approved,
            )
        except LoginRequestExpired:
            await self._bot.answer_callback_query(
                callback_query_id=callback_id, text=STALE_TEXT, show_alert=True
            )
            return
        await self._bot.answer_callback_query(callback_query_id=callback_id)
        message = callback.get("message")
        if isinstance(message, dict) and isinstance(message.get("chat"), dict):
            await self._bot.edit_message_text(
                chat_id=message["chat"].get("id"),
                message_id=message.get("message_id"),
                text=APPROVED_TEXT if approved else DENIED_TEXT,
            )


def _identity(sender: dict[str, Any]) -> TelegramIdentity:
    username = str(sender.get("username") or "")
    return TelegramIdentity(
        telegram_user_id=str(sender.get("id")),
        telegram_username=username,
        display_name=display_name_of(
            str(sender.get("first_name") or ""),
            str(sender.get("last_name") or ""),
            username,
        ),
    )
