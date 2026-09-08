import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest
from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError

from postify.adapters.telegram.account_login import (
    AccountLoginError,
    authorize,
    find_groups,
)


def client_for_qr(qr, *, authorized=False):
    return SimpleNamespace(
        connect=AsyncMock(),
        is_user_authorized=AsyncMock(return_value=authorized),
        qr_login=AsyncMock(return_value=qr),
        sign_in=AsyncMock(),
        disconnect=AsyncMock(),
    )


def test_existing_authorization_needs_neither_qr_nor_password():
    client = client_for_qr(None, authorized=True)
    show_qr = Mock()
    read_password = AsyncMock()

    assert asyncio.run(authorize(client, show_qr, read_password)) is None

    client.connect.assert_awaited_once_with()
    client.is_user_authorized.assert_awaited_once_with()
    client.qr_login.assert_not_awaited()
    client.sign_in.assert_not_awaited()
    show_qr.assert_not_called()
    read_password.assert_not_awaited()
    client.disconnect.assert_not_awaited()


def test_qr_success_waits_for_confirmation_without_requesting_password(capsys, caplog):
    qr = SimpleNamespace(url="tg://login?token=test-only-token", wait=AsyncMock(), recreate=AsyncMock())
    client = client_for_qr(qr)
    read_password = AsyncMock()
    shown = []

    asyncio.run(authorize(client, shown.append, read_password))

    assert shown == [qr.url]
    client.qr_login.assert_awaited_once_with()
    qr.wait.assert_awaited_once_with()
    qr.recreate.assert_not_awaited()
    read_password.assert_not_awaited()
    client.sign_in.assert_not_awaited()
    client.disconnect.assert_not_awaited()
    output = capsys.readouterr()
    assert "test-only-token" not in output.out + output.err + caplog.text


def test_expired_qr_is_recreated_and_the_new_url_is_shown_before_waiting():
    events = []
    class QR:
        url = "tg://login?token=expired"
        attempts = 0

        async def wait(self):
            events.append(("wait", self.url))
            self.attempts += 1
            if self.attempts == 1:
                raise asyncio.TimeoutError

        async def recreate(self):
            events.append(("recreate", self.url))
            self.url = "tg://login?token=fresh"

    client = client_for_qr(QR())
    read_password = AsyncMock()
    asyncio.run(authorize(client, lambda url: events.append(("show", url)), read_password))

    assert events == [
        ("show", "tg://login?token=expired"),
        ("wait", "tg://login?token=expired"),
        ("recreate", "tg://login?token=expired"),
        ("show", "tg://login?token=fresh"),
        ("wait", "tg://login?token=fresh"),
    ]
    client.qr_login.assert_awaited_once_with()
    read_password.assert_not_awaited()


def test_repeated_qr_expiry_stops_after_five_confirmation_attempts():
    qr = SimpleNamespace(url="tg://login?token=expired", wait=AsyncMock(side_effect=asyncio.TimeoutError), recreate=AsyncMock())
    client = client_for_qr(qr)
    shown = []
    read_password = AsyncMock()

    with pytest.raises(AccountLoginError) as caught:
        asyncio.run(authorize(client, shown.append, read_password))

    assert caught.value.code == "qr_login_expired"
    assert qr.wait.await_count == 5
    assert qr.recreate.await_count == 4
    assert len(shown) == 5
    read_password.assert_not_awaited()
    client.disconnect.assert_not_awaited()


def test_two_factor_wrong_password_can_be_corrected_without_restarting_qr(capsys, caplog):
    qr = SimpleNamespace(url="tg://login?token=two-factor", wait=AsyncMock(side_effect=SessionPasswordNeededError(request=None)), recreate=AsyncMock())
    client = client_for_qr(qr)
    client.sign_in.side_effect = [PasswordHashInvalidError(request=None), None]
    passwords = ["test-only-wrong-password", "test-only-correct-password"]
    read_password = AsyncMock(side_effect=passwords)
    shown = []

    assert asyncio.run(authorize(client, shown.append, read_password)) is None

    assert client.sign_in.await_args_list == [call(password=password) for password in passwords]
    assert read_password.await_count == 2
    assert shown == [qr.url]
    qr.wait.assert_awaited_once_with()
    qr.recreate.assert_not_awaited()
    output = capsys.readouterr()
    for password in passwords:
        assert password not in output.out + output.err + caplog.text


def test_two_factor_stops_after_three_wrong_passwords_without_exposing_them(capsys, caplog):
    qr = SimpleNamespace(url="tg://login?token=two-factor", wait=AsyncMock(side_effect=SessionPasswordNeededError(request=None)), recreate=AsyncMock())
    client = client_for_qr(qr)
    client.sign_in.side_effect = PasswordHashInvalidError(request=None)
    passwords = ["wrong-secret-one", "wrong-secret-two", "wrong-secret-three"]
    read_password = AsyncMock(side_effect=passwords)

    with pytest.raises(AccountLoginError) as caught:
        asyncio.run(authorize(client, Mock(), read_password))

    assert caught.value.code == "password_invalid"
    assert read_password.await_count == 3
    assert client.sign_in.await_args_list == [call(password=password) for password in passwords]
    client.disconnect.assert_not_awaited()
    output = capsys.readouterr()
    for password in passwords:
        assert password not in output.out + output.err + caplog.text + str(caught.value)


def test_connection_error_is_sanitized_and_disconnect_is_left_to_caller(capsys, caplog):
    client = client_for_qr(None)
    client.connect.side_effect = RuntimeError("PRIVATE_SESSION_SENTINEL")

    with pytest.raises(AccountLoginError) as caught:
        asyncio.run(authorize(client, Mock(), AsyncMock()))

    assert caught.value.code == "account_login_failed"
    assert caught.value.__suppress_context__ is True
    client.qr_login.assert_not_awaited()
    client.disconnect.assert_not_awaited()
    output = capsys.readouterr()
    assert "PRIVATE_SESSION_SENTINEL" not in output.out + output.err + caplog.text + str(caught.value)


def test_cancelled_login_propagates_cancellation_to_the_caller():
    qr = SimpleNamespace(url="tg://login?token=cancelled", wait=AsyncMock(side_effect=asyncio.CancelledError), recreate=AsyncMock())
    client = client_for_qr(qr)
    read_password = AsyncMock()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(authorize(client, Mock(), read_password))

    read_password.assert_not_awaited()
    qr.recreate.assert_not_awaited()
    client.disconnect.assert_not_awaited()


def test_group_search_normalizes_unicode_case_and_spaces_and_excludes_private_dialogs():
    title = "Ｃａｆｅ\u0301　NEWS — العربية"
    dialogs = [
        SimpleNamespace(id=-10011, title=title, is_group=True, is_channel=True),
        SimpleNamespace(id=-10012, title="Café News — Broadcast", is_group=False, is_channel=True),
        SimpleNamespace(id=-13, title="Other group", is_group=True, is_channel=False),
        SimpleNamespace(id=14, title="Café News — Private user", is_group=False, is_channel=False),
    ]
    async def iter_dialogs():
        for dialog in dialogs:
            yield dialog
    client = SimpleNamespace(iter_dialogs=iter_dialogs)

    found = asyncio.run(find_groups(client, "  CAFÉ\n NEWS  "))

    assert found == [
        {"id": -10011, "title": title, "type": "group"},
        {"id": -10012, "title": "Café News — Broadcast", "type": "channel"},
    ]


def test_group_search_uses_unicode_casefold_and_matches_inside_the_title():
    async def iter_dialogs():
        yield SimpleNamespace(id=-21, title="Berliner Straße — разговоры", is_group=True, is_channel=False)
    client = SimpleNamespace(iter_dialogs=iter_dialogs)

    assert asyncio.run(find_groups(client, "STRASSE")) == [
        {"id": -21, "title": "Berliner Straße — разговоры", "type": "group"}
    ]


def test_group_search_reports_iteration_errors_without_private_dialog_details(capsys, caplog):
    async def iter_dialogs():
        yield SimpleNamespace(id=-31, title="News", is_group=True, is_channel=False)
        raise RuntimeError("PRIVATE_DIALOG_SENTINEL")
    client = SimpleNamespace(iter_dialogs=iter_dialogs)

    with pytest.raises(AccountLoginError) as caught:
        asyncio.run(find_groups(client, "news"))

    assert caught.value.code == "group_search_failed"
    assert caught.value.__suppress_context__ is True
    output = capsys.readouterr()
    assert "PRIVATE_DIALOG_SENTINEL" not in output.out + output.err + caplog.text + str(caught.value)


@pytest.mark.parametrize("query", ["", " \n\t ", "\u3000\u00a0"])
def test_empty_group_query_is_rejected_before_requesting_any_dialogs(query):
    client = SimpleNamespace(iter_dialogs=Mock(side_effect=AssertionError("Empty query must not enumerate dialogs")))

    with pytest.raises(AccountLoginError) as caught:
        asyncio.run(find_groups(client, query))

    assert caught.value.code == "group_query_required"
    client.iter_dialogs.assert_not_called()
