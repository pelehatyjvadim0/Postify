from __future__ import annotations

from collections.abc import Callable
from datetime import datetime


class CheckChannel:
    """Runs a provider connection check and stores its observed status."""

    def __init__(self, repository, cipher, checker, *, clock: Callable[[], datetime]) -> None:
        self._repository = repository
        self._cipher = cipher
        self._checker = checker
        self._clock = clock

    def execute(self, project_id: int, channel_id: int) -> dict[str, object]:
        channel = self._repository.get_resource(project_id, "channels", channel_id)
        encrypted_secret = channel.get("encrypted_secret")
        if not isinstance(encrypted_secret, str) or self._cipher is None:
            raise RuntimeError("secret_storage_unavailable")
        status = self._checker.check(
            channel["configuration"], self._cipher.decrypt(encrypted_secret)
        )
        self._repository.set_channel_status(
            project_id, channel_id, status, self._clock()
        )
        return {"id": channel_id, "connectionStatus": status}
