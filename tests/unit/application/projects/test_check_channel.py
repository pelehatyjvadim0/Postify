from __future__ import annotations

from datetime import UTC, datetime

from postify.application.projects.check_channel import CheckChannel


NOW = datetime(2026, 8, 12, 10, tzinfo=UTC)


def test_check_channel_decrypts_configured_secret_and_persists_actual_result() -> None:
    # Break caught: UI reports a configured channel as checked without calling the provider.
    events: list[tuple[object, ...]] = []

    class Repository:
        def get_resource(self, project_id: int, resource: str, resource_id: int):
            assert (project_id, resource, resource_id) == (1, "channels", 2)
            return {"provider": "telegram", "configuration": {"chat_id": "-100"}, "encrypted_secret": "cipher"}

        def set_channel_status(self, project_id: int, channel_id: int, status: str, now):
            events.append((project_id, channel_id, status, now))

    class Cipher:
        def decrypt(self, value: str) -> str:
            assert value == "cipher"
            return "token"

    class Checker:
        last_reason = ""

        def check(self, configuration: dict[str, object], secret: str) -> str:
            assert configuration == {"chat_id": "-100"}
            assert secret == "token"
            return "ok"

    result = CheckChannel(Repository(), Cipher(), Checker(), clock=lambda: NOW).execute(1, 2)

    assert result == {"id": 2, "connectionStatus": "ok", "reason": ""}
    assert events == [(1, 2, "ok", NOW)]
