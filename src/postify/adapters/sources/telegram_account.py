"""Read account-visible Telegram messages without prompting or sending messages."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from postify.adapters.sources.telegram_group import TelegramMessage
from postify.application.ports.candidate_source import SourceFetchError
from postify.infrastructure.security.telegram_session import TelegramSessionError as SessionError, session_lock


class TelegramAccountReader:
    def __init__(
        self, *, api_id: int, api_hash: str,
        last_message_id: Callable[[str], int | None],
        initialize: Callable[[str, int], int],
        session_directory: Path = Path("/data/telegram"),
        client_factory=None,
    ):
        self._api_id = api_id
        self._api_hash = api_hash
        self._last_message_id = last_message_id
        self._initialize = initialize
        self._session_directory = session_directory
        self._client_factory = client_factory

    def __call__(self, group_id: str) -> tuple[TelegramMessage, ...]:
        try:
            int(group_id)
            watermark = self._last_message_id(group_id)
            if watermark is not None and (type(watermark) is not int or watermark < 0):
                raise ValueError("invalid persisted position")
            with session_lock(self._session_directory) as session:
                return asyncio.run(self._bounded_read(session, group_id, watermark))
        except SourceFetchError:
            raise
        except SessionError as error:
            raise SourceFetchError(str(error)) from None
        except TimeoutError:
            raise SourceFetchError("telegram_source_timeout") from None
        except Exception:
            raise SourceFetchError("telegram_account_unavailable") from None

    async def _bounded_read(self, session, group_id, watermark):
        return await asyncio.wait_for(self._read(session, group_id, watermark), timeout=60)

    async def _read(self, session, group_id, watermark):
        factory = self._client_factory
        if factory is None:
            from telethon import TelegramClient
            factory = TelegramClient
        client = factory(str(session), self._api_id, self._api_hash)
        try:
            # Reserve five seconds of the full operation budget for disconnect.
            return await asyncio.wait_for(self._messages(client, group_id, watermark), timeout=55)
        finally:
            await asyncio.wait_for(client.disconnect(), timeout=5)

    async def _messages(self, client, group_id, watermark):
        await client.connect()
        if not await client.is_user_authorized():
            raise SourceFetchError("telegram_account_not_authorized")
        entity = await client.get_input_entity(int(group_id))
        if watermark is None:
            latest = [message async for message in client.iter_messages(entity, limit=100)]
            boundary = min(message.id for message in latest) - 1 if latest else 0
            # Persist the initial window even when it contains no usable text.
            # initialize returns the winning boundary if another import got here first.
            watermark = self._initialize(group_id, boundary)
            if type(watermark) is not int or watermark < 0:
                raise ValueError("invalid initial position")
        options = {"min_id": watermark, "reverse": True, "limit": None}
        messages = []
        async for message in client.iter_messages(entity, **options):
            content = message.raw_text
            if message.action is not None or not isinstance(content, str) or not content.strip():
                continue
            messages.append(TelegramMessage(message.id, content, message.date))
            if len(messages) == 100:
                break
        return tuple(sorted(messages, key=lambda item: item.message_id))
