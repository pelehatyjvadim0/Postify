"""Telegram mapping; transport is supplied only after group access is configured.

The reader owns Telegram-specific pagination. Fetch must be replayable: import
commits materials separately and deduplicates by connection + external ID.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from postify.application.ports.candidate_source import SourceFetchError
from postify.domain.candidates.models import Candidate


@dataclass(frozen=True, slots=True)
class TelegramMessage:
    message_id: int
    text: str
    published_at: datetime | None = None
    url: str = ""


class TelegramGroupSource:
    def __init__(self, *, connection_id: int, group_id: str,
                 reader: Callable[[str], Sequence[TelegramMessage]] | None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._connection_id = connection_id
        self._group_id = group_id
        self._reader = reader
        self._clock = clock

    def fetch(self) -> tuple[Candidate, ...]:
        if self._reader is None:
            raise SourceFetchError("source_access_not_configured")
        try:
            messages = self._reader(self._group_id)
            candidates = []
            for message in messages:
                if type(message.message_id) is not int or message.message_id < 1:
                    raise ValueError("invalid message id")
                if not isinstance(message.text, str):
                    raise ValueError("invalid message text")
                if not message.text.strip():
                    continue  # Service messages and attachments without text are not text materials.
                candidates.append(Candidate(
                    source_name="telegram_group", source_id=f"{self._group_id}:{message.message_id}",
                    source_connection_id=self._connection_id,
                    title=message.text.strip().splitlines()[0][:200],
                    url=message.url, discovered_at=self._clock(),
                    source_text=message.text, published_at=message.published_at,
                    raw_payload={"group_id": self._group_id, "message_id": message.message_id},
                ))
            return tuple(candidates)
        except Exception:
            raise SourceFetchError("telegram_source_failed") from None
